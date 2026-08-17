from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from control.models import (
    ParameterCategory,
    ParameterDefinition,
    ParameterValue,
    validate_parameter_value,
)


class ParameterValidationTests(SimpleTestCase):
    def test_category_code_is_normalized(self):
        category = ParameterCategory(code=' LLM ', name='LLM')

        category.clean()

        self.assertEqual(category.code, 'llm')

    def test_definition_identity_is_normalized(self):
        definition = self._definition(service=' FastAPI ', key=' log_level ')

        definition.clean()

        self.assertEqual(definition.service, 'fastapi')
        self.assertEqual(definition.key, 'LOG_LEVEL')

    def test_secret_definition_must_use_environment(self):
        definition = self._definition(
            source=ParameterDefinition.Source.DATABASE,
            is_secret=True,
        )

        with self.assertRaises(ValidationError):
            definition.clean()

    def test_secret_definition_cannot_have_default(self):
        definition = self._definition(
            source=ParameterDefinition.Source.ENVIRONMENT,
            is_secret=True,
            default_value='secret',
        )

        with self.assertRaises(ValidationError):
            definition.clean()

    def test_environment_definition_cannot_have_stored_value(self):
        definition = self._definition(source=ParameterDefinition.Source.ENVIRONMENT)
        value = ParameterValue(
            definition=definition,
            environment=ParameterValue.Environment.PRODUCTION,
            value='example',
        )

        with self.assertRaises(ValidationError):
            value.clean()

    def test_integer_rejects_boolean(self):
        with self.assertRaises(ValidationError):
            validate_parameter_value(
                True,
                ParameterDefinition.DataType.INTEGER,
                {},
            )

    def test_numeric_range_is_validated(self):
        with self.assertRaises(ValidationError):
            validate_parameter_value(
                1801,
                ParameterDefinition.DataType.INTEGER,
                {'min': 1, 'max': 1800},
            )

    def test_allowed_choices_are_validated(self):
        with self.assertRaises(ValidationError):
            validate_parameter_value(
                'TRACE',
                ParameterDefinition.DataType.STRING,
                {'choices': ['INFO', 'WARNING', 'ERROR']},
            )

    def test_unknown_validation_rule_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_parameter_value(
                'INFO',
                ParameterDefinition.DataType.STRING,
                {'choice': ['INFO']},
            )

    def test_invalid_numeric_rule_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_parameter_value(
                120,
                ParameterDefinition.DataType.INTEGER,
                {'min': '1'},
            )

    @staticmethod
    def _definition(**overrides):
        values = {
            'category': ParameterCategory(code='general', name='General'),
            'service': 'fastapi',
            'key': 'EXAMPLE',
            'label': 'Example',
            'data_type': ParameterDefinition.DataType.STRING,
            'validation_rules': {},
            'source': ParameterDefinition.Source.DATABASE,
        }
        values.update(overrides)
        return ParameterDefinition(**values)
