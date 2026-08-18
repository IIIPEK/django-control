from __future__ import annotations

import json
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings

from control.models import (
    AccessRole,
    AccessRoleScope,
    ApiCredential,
    ApiCredentialRole,
    ApiScope,
    SqlAccessProfile,
    SqlCredentialProfile,
    SqlQuery,
    SqlQueryCategory,
    SqlQueryGrant,
    SqlQueryPublication,
    SqlQueryRevision,
)


@override_settings(CONFIG_API_KEY='test-service-token')
class SqlCatalogTests(TestCase):
    def setUp(self):
        self.category = SqlQueryCategory.objects.create(
            code='finance',
            name='Finance',
            description='Financial reporting queries.',
        )
        self.query = SqlQuery.objects.create(
            key='q-03',
            category=self.category,
            title='Opening balances',
            description='Returns opening balances by account.',
        )
        self.revision = SqlQueryRevision.objects.create(
            query=self.query,
            sql_text='SELECT account, balance FROM balances',
            parameters={'year': {'type': 'integer'}},
            result_description='Account opening balances.',
            comment='Initial import.',
        )
        self.publication = SqlQueryPublication.objects.create(
            query=self.query,
            environment='production',
            revision=self.revision,
            default_limit=1000,
            max_limit=5000,
        )
        self.profile = SqlAccessProfile.objects.create(
            environment='production',
            code='finance',
            name='Finance',
            description='Finance query access.',
        )
        SqlQueryGrant.objects.create(profile=self.profile, query=self.query)

    def test_revision_is_numbered_hashed_and_immutable(self):
        self.assertEqual(self.revision.revision, 1)
        self.assertEqual(len(self.revision.checksum), 64)

        self.revision.comment = 'Changed after creation.'
        with self.assertRaises(ValidationError):
            self.revision.save()

    def test_publication_rejects_revision_from_another_query(self):
        other = SqlQuery.objects.create(
            key='Q-04',
            category=self.category,
            title='Purchase book',
            description='Returns purchase book entries.',
        )
        publication = SqlQueryPublication(
            query=other,
            environment='staging',
            revision=self.revision,
        )

        with self.assertRaises(ValidationError):
            publication.clean()

    def test_sql_profile_environment_must_match_credential(self):
        credential = ApiCredential(
            environment='staging',
            name='Staging client',
            role=ApiCredential.Role.CLIENT,
        )
        credential.set_key('a' * 32)
        credential.save()

        with self.assertRaises(ValidationError):
            SqlCredentialProfile.objects.create(
                credential=credential,
                profile=self.profile,
            )

    def test_sql_catalog_endpoint_returns_published_query_and_etag(self):
        response = self.client.get(
            '/api/v1/sql-catalog/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['schema_version'], 1)
        self.assertEqual(payload['queries'][0]['key'], 'Q-03')
        self.assertEqual(payload['queries'][0]['revision'], 1)
        self.assertEqual(payload['queries'][0]['profiles'], ['finance'])
        self.assertEqual(
            payload['queries'][0]['sql'],
            'SELECT account, balance FROM balances',
        )

        cached = self.client.get(
            '/api/v1/sql-catalog/production/',
            headers={
                'Authorization': 'Bearer test-service-token',
                'If-None-Match': response.headers['ETag'],
            },
        )
        self.assertEqual(cached.status_code, 304)

    def test_credentials_payload_contains_roles_scopes_and_sql_profiles(self):
        scope = ApiScope.objects.get(code='sql.query.execute')
        role = AccessRole.objects.get(code='sql-consumer')
        self.assertTrue(AccessRoleScope.objects.filter(role=role, scope=scope).exists())
        credential = ApiCredential(
            environment='production',
            name='Finance API',
            role=ApiCredential.Role.CLIENT,
        )
        credential.set_key('b' * 32)
        credential.save()
        ApiCredentialRole.objects.create(credential=credential, role=role)
        SqlCredentialProfile.objects.create(
            credential=credential,
            profile=self.profile,
        )

        response = self.client.get(
            '/api/v1/credentials/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()['credentials'][0]
        self.assertEqual(item['roles'], ['sql-consumer'])
        self.assertEqual(
            item['scopes'],
            ['sql.catalog.read', 'sql.query', 'sql.query.execute'],
        )
        self.assertEqual(item['sql_profiles'], ['finance'])


class SyncSqlCatalogCommandTests(TestCase):
    def test_command_imports_registry_sql_publication_profile_and_grant(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'q01.sql').write_text(
                'CREATE OR REPLACE VARIABLE @year INTEGER;\n'
                'SET @year = COALESCE(@year, 2026);\n'
                'SELECT @year AS year_value',
                encoding='utf-8',
            )
            registry_path = root / 'registry.json'
            registry_path.write_text(
                json.dumps(
                    {
                        'queries': [
                            {
                                'key': 'Q-01',
                                'section': 'service',
                                'status': 'active',
                                'title': 'Database channel check',
                                'description': 'Checks database connectivity.',
                                'file': 'q01.sql',
                            }
                        ]
                    }
                ),
                encoding='utf-8',
            )

            call_command(
                'sync_sql_catalog',
                registry_file=registry_path,
                environment='production',
                verbosity=0,
            )
            call_command(
                'sync_sql_catalog',
                registry_file=registry_path,
                environment='production',
                verbosity=0,
            )

        query = SqlQuery.objects.get(key='Q-01')
        publication = SqlQueryPublication.objects.get(
            query=query,
            environment='production',
        )
        profile = SqlAccessProfile.objects.get(
            code='service',
            environment='production',
        )
        self.assertIn('SELECT @year AS year_value', publication.revision.sql_text)
        self.assertEqual(
            publication.revision.parameters['year'],
            {
                'type': 'INTEGER',
                'default': '2026',
                'description': 'Query parameter.',
            },
        )
        self.assertEqual(SqlQueryRevision.objects.filter(query=query).count(), 1)
        self.assertTrue(
            SqlQueryGrant.objects.filter(profile=profile, query=query).exists()
        )
