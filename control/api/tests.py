from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

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
