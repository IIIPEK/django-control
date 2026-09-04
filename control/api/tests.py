from types import SimpleNamespace
from io import StringIO
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from control.api.services import build_effective_config
from control.models import ParameterDefinition


class EffectiveConfigPayloadTests(SimpleTestCase):
    def test_payload_uses_stored_value_before_default(self):
        definition = self._definition(
            key='LOG_LEVEL',
            default_value='WARNING',
            effective_values=[SimpleNamespace(value='INFO')],
        )

        payload = build_effective_config(
            [definition],
            environment='production',
            services=['fastapi'],
        )

        self.assertEqual(payload['values']['fastapi']['LOG_LEVEL'], 'INFO')
        self.assertEqual(len(payload['version']), 64)

    def test_payload_uses_default_when_value_is_missing(self):
        definition = self._definition(
            key='REQUEST_TIMEOUT',
            default_value=600,
        )

        payload = build_effective_config(
            [definition],
            environment='production',
            services=['fastapi'],
        )

        self.assertEqual(payload['values']['fastapi']['REQUEST_TIMEOUT'], 600)

    def test_required_value_without_default_is_reported(self):
        definition = self._definition(
            key='CLASSIFICATION_LLM_URL',
            is_required=True,
        )

        payload = build_effective_config(
            [definition],
            environment='production',
            services=['fastapi'],
        )

        self.assertEqual(
            payload['missing_required']['fastapi'],
            ['CLASSIFICATION_LLM_URL'],
        )

    def test_secret_and_environment_definitions_are_excluded(self):
        secret = self._definition(
            key='API_KEY',
            is_secret=True,
            source=ParameterDefinition.Source.ENVIRONMENT,
            effective_values=[SimpleNamespace(value='must-not-leak')],
        )
        environment = self._definition(
            key='PG_HOST',
            source=ParameterDefinition.Source.ENVIRONMENT,
            effective_values=[SimpleNamespace(value='must-not-leak')],
        )

        payload = build_effective_config(
            [secret, environment],
            environment='production',
            services=['fastapi'],
        )

        self.assertEqual(payload['values']['fastapi'], {})

    @staticmethod
    def _definition(**overrides):
        values = {
            'service': 'fastapi',
            'key': 'EXAMPLE',
            'source': ParameterDefinition.Source.DATABASE,
            'is_secret': False,
            'is_required': False,
            'requires_restart': True,
            'default_value': None,
            'effective_values': [],
        }
        values.update(overrides)
        return SimpleNamespace(**values)


@override_settings(CONFIG_API_KEY='test-service-token')
class TeamsConfigAPITests(TestCase):
    def test_teams_graph_config_is_returned_without_client_secret(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / 'teams.env'
            env_path.write_text(
                'TEAMS_GRAPH_TENANT_ID=tenant-id\n'
                'TEAMS_GRAPH_CLIENT_ID=client-id\n'
                'TEAMS_GRAPH_CLIENT_SECRET=must-not-leak\n'
                'TEAMS_GRAPH_ALLOWED_TEAM_IDS=team-1,team-2\n',
                encoding='utf-8',
            )
            call_command(
                'sync_fastapi_catalog',
                env_file=env_path,
                environment='production',
                stdout=StringIO(),
            )

        response = self.client.get(
            '/api/v1/config/production/?service=teams-graph',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 200)
        values = response.json()['values']['teams-graph']
        self.assertEqual(values['TEAMS_GRAPH_TENANT_ID'], 'tenant-id')
        self.assertEqual(values['TEAMS_GRAPH_CLIENT_ID'], 'client-id')
        self.assertEqual(values['TEAMS_GRAPH_DEFAULT_SCOPE'], 'https://graph.microsoft.com/.default')
        self.assertEqual(values['TEAMS_GRAPH_ALLOWED_TEAM_IDS'], 'team-1,team-2')
        self.assertEqual(values['TEAMS_GRAPH_MAX_DAYS_BACK'], 30)
        self.assertEqual(values['TEAMS_GRAPH_MAX_RESULTS'], 50)
        self.assertIs(values['TEAMS_GRAPH_ATTACHMENTS_ENABLED'], True)
        self.assertNotIn('TEAMS_GRAPH_CLIENT_SECRET', values)


@override_settings(CONFIG_API_KEY='test-service-token')
class ConfigAPIRequestValidationTests(SimpleTestCase):
    def test_missing_token_is_unauthorized(self):
        response = self.client.get('/api/v1/config/production/?service=fastapi')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['WWW-Authenticate'], 'Bearer')

    def test_invalid_token_is_unauthorized(self):
        response = self.client.get(
            '/api/v1/config/production/?service=fastapi',
            headers={'Authorization': 'Bearer invalid'},
        )

        self.assertEqual(response.status_code, 401)

    def test_unknown_environment_is_rejected_before_database_access(self):
        response = self.client.get(
            '/api/v1/config/invalid/?service=fastapi',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 404)

    def test_service_is_required(self):
        response = self.client.get(
            '/api/v1/config/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_service_name_is_rejected(self):
        response = self.client.get(
            '/api/v1/config/production/?service=FastAPI!',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 400)

    def test_write_method_is_not_allowed(self):
        response = self.client.post(
            '/api/v1/config/production/?service=fastapi',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 405)

    def test_mail_credentials_require_authentication(self):
        response = self.client.get('/api/v1/credentials/mail/production/')

        self.assertEqual(response.status_code, 401)

    def test_mail_credentials_reject_unknown_environment(self):
        response = self.client.get(
            '/api/v1/credentials/mail/invalid/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 404)

    def test_mail_credentials_are_read_only(self):
        response = self.client.post(
            '/api/v1/credentials/mail/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 405)

    def test_credentials_require_authentication(self):
        response = self.client.get('/api/v1/credentials/production/')

        self.assertEqual(response.status_code, 401)

    def test_credentials_reject_unknown_environment(self):
        response = self.client.get(
            '/api/v1/credentials/invalid/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 404)

    def test_credentials_are_read_only(self):
        response = self.client.post(
            '/api/v1/credentials/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 405)

    def test_sql_catalog_requires_authentication(self):
        response = self.client.get('/api/v1/sql-catalog/production/')

        self.assertEqual(response.status_code, 401)

    def test_sql_catalog_rejects_unknown_environment(self):
        response = self.client.get(
            '/api/v1/sql-catalog/invalid/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 404)

    def test_sql_catalog_is_read_only(self):
        response = self.client.post(
            '/api/v1/sql-catalog/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 405)
