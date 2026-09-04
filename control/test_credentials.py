from types import SimpleNamespace
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from control.api.credential_services import build_credentials, build_mail_credentials
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

    def test_teams_policy_is_normalized(self):
        credential = ApiCredential(
            environment='production',
            name='Teams agent',
            role=ApiCredential.Role.AGENT,
            policy={
                'allowed_user_ids': [' user-1 ', 'user-1'],
                'allowed_team_ids': ['team-1'],
                'max_days_back': 14,
            },
        )
        credential.set_key('a' * 32)

        credential.clean()

        self.assertEqual(
            credential.policy,
            {
                'allowed_user_ids': ['user-1'],
                'allowed_team_ids': ['team-1'],
                'max_days_back': 14,
            },
        )

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

    def test_mark_read_permission_is_allowed(self):
        credential = ApiCredential(
            environment='production',
            name='Mail status agent',
            role=ApiCredential.Role.AGENT,
        )
        policy = MailAgentPolicy(
            credential=credential,
            mailboxes=['bot@example.com'],
            permissions=['mail.mark_read'],
        )

        policy.clean()

        self.assertEqual(policy.permissions, ['mail.mark_read'])

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

    def test_payload_contains_mark_read_permission(self):
        policy = SimpleNamespace(
            mailboxes=['bot@example.com'],
            permissions=['mail.mark_read'],
            recipient_domains=[],
        )
        credential = SimpleNamespace(
            key_id='0123456789ab',
            key_hash='0' * 64,
            hash_algorithm='sha256',
            name='Mail status agent',
            role='agent',
            scopes=['mail.api'],
            mail_policy=policy,
            expires_at=None,
        )

        payload = build_mail_credentials([credential])

        self.assertEqual(
            payload['credentials'][0]['permissions'],
            ['mail.mark_read'],
        )

    def test_general_payload_contains_teams_policy(self):
        credential = SimpleNamespace(
            key_id='0123456789ab',
            key_hash='0' * 64,
            hash_algorithm='sha256',
            name='Teams agent',
            role='agent',
            roles=['teams-agent'],
            scopes=['teams.messages.read'],
            sql_profiles=[],
            policy={'allowed_team_ids': ['team-1'], 'max_days_back': 14},
            expires_at=None,
        )

        payload = build_credentials([credential])

        self.assertEqual(
            payload['credentials'][0]['policy'],
            {'allowed_team_ids': ['team-1'], 'max_days_back': 14},
        )

    def test_mail_compatibility_payload_does_not_add_policy(self):
        credential = SimpleNamespace(
            key_id='0123456789ab',
            key_hash='0' * 64,
            hash_algorithm='sha256',
            name='Mail agent',
            role='agent',
            roles=['mail-agent'],
            scopes=['mail.api'],
            sql_profiles=[],
            policy={'allowed_team_ids': ['team-1']},
            expires_at=None,
        )

        payload = build_mail_credentials([credential])

        self.assertNotIn('policy', payload['credentials'][0])


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

    def test_admin_form_saves_teams_policy_fields(self):
        role = AccessRole.objects.get(code='teams-agent')
        form = ApiCredentialAdminForm(
            data={
                'environment': 'production',
                'name': 'Teams MCP agent',
                'description': '',
                'role': ApiCredential.Role.AGENT,
                'selected_access_roles': [role.pk],
                'selected_sql_profiles': [],
                'is_active': True,
                'expires_at': '',
                'raw_key': 't' * 32,
                'generate_key': False,
                'teams_allowed_user_ids': 'user-1\nuser-2',
                'teams_allowed_user_principals': 'agent@example.com',
                'teams_allowed_team_ids': 'team-1',
                'teams_allowed_channel_ids': 'channel-1',
                'teams_allowed_chat_ids': 'chat-1',
                'teams_max_days_back': '14',
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        credential = form.save()
        self.assertEqual(credential.access_role_codes(), ['teams-agent'])
        self.assertEqual(
            credential.policy,
            {
                'allowed_user_ids': ['user-1', 'user-2'],
                'allowed_user_principals': ['agent@example.com'],
                'allowed_team_ids': ['team-1'],
                'allowed_channel_ids': ['channel-1'],
                'allowed_chat_ids': ['chat-1'],
                'max_days_back': 14,
            },
        )


@override_settings(CONFIG_API_KEY='test-service-token')
class TeamsCredentialAPITests(TestCase):
    def setUp(self):
        self.teams_role = AccessRole.objects.get(code='teams-agent')

    def _credential(self, *, name, raw_key, is_active=True, expires_at=None):
        credential = ApiCredential(
            environment='production',
            name=name,
            role=ApiCredential.Role.AGENT,
            policy={
                'allowed_user_ids': ['user-1'],
                'allowed_user_principals': ['agent@example.com'],
                'allowed_team_ids': ['team-1'],
                'allowed_channel_ids': ['channel-1'],
                'allowed_chat_ids': ['chat-1'],
                'max_days_back': 14,
            },
            is_active=is_active,
            expires_at=expires_at,
        )
        credential.set_key(raw_key)
        credential.save()
        ApiCredentialRole.objects.create(
            credential=credential,
            role=self.teams_role,
        )
        return credential

    def test_credentials_api_returns_active_teams_credential(self):
        active = self._credential(name='Active Teams', raw_key='a' * 32)
        self._credential(
            name='Disabled Teams',
            raw_key='b' * 32,
            is_active=False,
        )
        self._credential(
            name='Expired Teams',
            raw_key='c' * 32,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.get(
            '/api/v1/credentials/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['credentials']), 1)
        item = response.json()['credentials'][0]
        self.assertEqual(item['key_id'], active.key_id)
        self.assertNotIn('raw_key', item)
        self.assertEqual(item['roles'], ['teams-agent'])
        self.assertEqual(
            item['scopes'],
            [
                'teams.attachments.read',
                'teams.messages.read',
                'teams.messages.search',
            ],
        )
        self.assertEqual(item['policy']['allowed_team_ids'], ['team-1'])
        self.assertEqual(item['policy']['max_days_back'], 14)

    def test_mail_credentials_api_keeps_legacy_payload_shape(self):
        mail_role = AccessRole.objects.get(code='mail-agent')
        credential = ApiCredential(
            environment='production',
            name='Mail agent',
            role=ApiCredential.Role.AGENT,
        )
        credential.set_key('m' * 32)
        credential.save()
        ApiCredentialRole.objects.create(credential=credential, role=mail_role)
        MailAgentPolicy.objects.create(
            credential=credential,
            mailboxes=['mail@example.com'],
            permissions=['mail.read'],
            recipient_domains=['example.com'],
        )

        response = self.client.get(
            '/api/v1/credentials/mail/production/',
            headers={'Authorization': 'Bearer test-service-token'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['credentials']), 1)
        item = response.json()['credentials'][0]
        self.assertEqual(item['key_id'], credential.key_id)
        self.assertEqual(item['permissions'], ['mail.read'])
        self.assertNotIn('policy', item)
