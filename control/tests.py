from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from control.catalogs.fastapi import (
    CATEGORIES,
    PARAMETERS,
    PARAMETERS_BY_KEY,
    parse_env_value,
)
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


class FastAPICatalogTests(SimpleTestCase):
    def test_parameter_keys_are_unique(self):
        self.assertEqual(len(PARAMETERS), len(PARAMETERS_BY_KEY))

    def test_all_category_references_exist(self):
        category_codes = {category.code for category in CATEGORIES}

        self.assertFalse(
            {parameter.category for parameter in PARAMETERS} - category_codes
        )

    def test_catalog_defaults_are_valid(self):
        categories = {
            category.code: ParameterCategory(code=category.code, name=category.name)
            for category in CATEGORIES
        }
        for spec in PARAMETERS:
            definition = ParameterDefinition(
                category=categories[spec.category],
                service=spec.service,
                key=spec.key,
                label=spec.label,
                description=spec.description,
                data_type=spec.data_type,
                default_value=spec.default_value,
                validation_rules=spec.validation_rules,
                source=spec.source,
                is_secret=spec.is_secret,
                is_required=spec.is_required,
                requires_restart=spec.requires_restart,
                sort_order=spec.sort_order,
            )
            with self.subTest(key=spec.key):
                definition.clean()

    def test_placeholder_is_not_imported(self):
        spec = PARAMETERS_BY_KEY['MAIL_GRAPH_TENANT_ID']

        with self.assertRaises(ValidationError):
            parse_env_value(spec, '<tenant>')

    def test_boolean_value_is_parsed(self):
        spec = PARAMETERS_BY_KEY['WHISPER_DIARIZATION_ENABLED']

        self.assertIs(parse_env_value(spec, 'true'), True)
