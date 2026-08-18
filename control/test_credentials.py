from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from control.api.credential_services import build_mail_credentials
from control.forms import ApiCredentialAdminForm
from control.models import (
    API_KEY_HASH_ALGORITHM,
    AccessRole,
    AccessRoleScope,
    ApiCredentialRole,
    ApiScope,
    ApiCredential,
    MailAgentPolicy,
    SqlAccessProfile,
    api_key_digest,
    generate_api_key,
)


class ApiCredentialHashTests(SimpleTestCase):
    def test_key_is_stored_as_sha256_digest(self):
        raw_key = 'a' * 32
        credential = ApiCredential(
            environment='production',
            name='Mail agent',
            role=ApiCredential.Role.AGENT,
        )

        credential.set_key(raw_key)

        self.assertEqual(credential.key_hash, api_key_digest(raw_key))
        self.assertEqual(credential.key_id, credential.key_hash[:12])
        self.assertEqual(credential.hash_algorithm, API_KEY_HASH_ALGORITHM)
        self.assertTrue(credential.matches_key(raw_key))
        self.assertFalse(credential.matches_key('b' * 32))

    def test_short_manual_key_is_rejected(self):
        with self.assertRaises(ValidationError):
            api_key_digest('too-short')

    def test_generated_key_has_required_length(self):
        self.assertGreaterEqual(len(generate_api_key()), 32)

class MailAgentPolicyValidationTests(SimpleTestCase):
    def test_policy_values_are_normalized_and_deduplicated(self):
        credential = ApiCredential(
            environment='production',
            name='Mail agent',
            role=ApiCredential.Role.AGENT,
        )
        policy = MailAgentPolicy(
            credential=credential,
            mailboxes=['BOT@EXAMPLE.COM', 'bot@example.com'],
            permissions=['mail.read', 'mail.read'],
            recipient_domains=['@EXAMPLE.COM', '*'],
        )

        policy.clean()

        self.assertEqual(policy.mailboxes, ['bot@example.com'])
        self.assertEqual(policy.permissions, ['mail.read'])
        self.assertEqual(policy.recipient_domains, ['example.com', '*'])

    def test_unknown_permission_is_rejected(self):
        credential = ApiCredential(
            environment='production',
            name='Mail agent',
            role=ApiCredential.Role.AGENT,
        )
        policy = MailAgentPolicy(
            credential=credential,
            mailboxes=['bot@example.com'],
            permissions=['mail.delete-everything'],
        )

        with self.assertRaises(ValidationError):
            policy.clean()


class MailCredentialPayloadTests(SimpleTestCase):
    def test_payload_contains_hash_and_normalized_policy(self):
        policy = SimpleNamespace(
            mailboxes=['bot@example.com'],
            permissions=['mail.read'],
            recipient_domains=['example.com'],
        )
        credential = SimpleNamespace(
            key_id='0123456789ab',
            key_hash='0' * 64,
            hash_algorithm='sha256',
            name='Mail agent',
            role='agent',
            scopes=['mail.api'],
            mail_policy=policy,
            expires_at=None,
        )

        payload = build_mail_credentials([credential])

        self.assertEqual(payload['schema_version'], 2)
        self.assertEqual(payload['credentials'][0]['key_hash'], '0' * 64)
        self.assertEqual(payload['credentials'][0]['scopes'], ['mail.api'])
        self.assertEqual(
            payload['credentials'][0]['permissions'],
            ['mail.read'],
        )
        self.assertEqual(len(payload['version']), 64)


class NormalizedCredentialAccessTests(TestCase):
    def test_effective_scopes_are_inherited_from_active_roles(self):
        scope = ApiScope.objects.get(code='sql.query.execute')
        role = AccessRole.objects.get(code='sql-consumer')
        self.assertTrue(AccessRoleScope.objects.filter(role=role, scope=scope).exists())
        credential = ApiCredential(
            environment='production',
            name='SQL client',
            role=ApiCredential.Role.CLIENT,
        )
        credential.set_key('a' * 32)
        credential.save()
        ApiCredentialRole.objects.create(credential=credential, role=role)

        self.assertEqual(
            credential.scopes,
            ['sql.catalog.read', 'sql.query', 'sql.query.execute'],
        )
        self.assertEqual(credential.access_role_codes(), ['sql-consumer'])

        role.is_active = False
        role.save()
        self.assertEqual(credential.scopes, [])

    def test_admin_form_assigns_roles_and_same_environment_sql_profiles(self):
        role = AccessRole.objects.get(code='sql-consumer')
        profile = SqlAccessProfile.objects.create(
            environment='production',
            code='finance',
            name='Finance',
        )
        form = ApiCredentialAdminForm(
            data={
                'environment': 'production',
                'name': 'Finance API',
                'description': '',
                'role': ApiCredential.Role.CLIENT,
                'selected_access_roles': [role.pk],
                'selected_sql_profiles': [profile.pk],
                'is_active': True,
                'expires_at': '',
                'raw_key': 'a' * 32,
                'generate_key': False,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        credential = form.save()
        self.assertEqual(credential.access_role_codes(), ['sql-consumer'])
        self.assertEqual(credential.sql_profile_codes(), ['finance'])
