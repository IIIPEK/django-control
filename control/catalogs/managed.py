from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.core.exceptions import ImproperlyConfigured, ValidationError


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_DIR = Path(__file__).with_name('manifests')
_MANIFEST_FIELDS = frozenset({'schema_version', 'service', 'categories', 'parameters'})
_CATEGORY_FIELDS = frozenset({'code', 'name', 'description', 'sort_order'})
_PARAMETER_FIELDS = frozenset(
    {
        'key', 'category', 'service', 'label', 'description', 'data_type',
        'default_value', 'validation_rules', 'source', 'is_secret',
        'is_required', 'requires_restart', 'sort_order',
    }
)
_DATA_TYPES = frozenset({'string', 'integer', 'float', 'boolean', 'url', 'json'})
_SOURCES = frozenset({'database', 'env', 'default'})


@dataclass(frozen=True)
class CategorySpec:
    code: str
    name: str
    description: str
    sort_order: int


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    category: str
    service: str
    label: str
    description: str
    data_type: str = 'string'
    default_value: Any = None
    validation_rules: dict[str, Any] = field(default_factory=dict)
    source: str = 'database'
    is_secret: bool = False
    is_required: bool = False
    requires_restart: bool = True
    sort_order: int = 0


def _manifest_error(path: Path, message: str) -> ImproperlyConfigured:
    return ImproperlyConfigured(f'Invalid managed catalog manifest {path.name}: {message}')


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise _manifest_error(path, str(exc)) from exc
    if not isinstance(payload, dict):
        raise _manifest_error(path, 'root must be a JSON object.')
    unknown = sorted(set(payload) - _MANIFEST_FIELDS)
    if unknown:
        raise _manifest_error(path, f'unknown root fields: {", ".join(unknown)}.')
    if payload.get('schema_version') != MANIFEST_SCHEMA_VERSION:
        raise _manifest_error(path, f'schema_version must be {MANIFEST_SCHEMA_VERSION}.')
    return payload


def _category_from_json(path: Path, raw: Any) -> CategorySpec:
    if not isinstance(raw, dict):
        raise _manifest_error(path, 'each category must be a JSON object.')
    unknown = sorted(set(raw) - _CATEGORY_FIELDS)
    missing = sorted(_CATEGORY_FIELDS - set(raw))
    if unknown or missing:
        details = []
        if unknown:
            details.append(f'unknown category fields: {", ".join(unknown)}')
        if missing:
            details.append(f'missing category fields: {", ".join(missing)}')
        raise _manifest_error(path, '; '.join(details) + '.')
    if not all(isinstance(raw[name], str) for name in ('code', 'name', 'description')):
        raise _manifest_error(path, 'category code, name, and description must be strings.')
    if not isinstance(raw['sort_order'], int) or isinstance(raw['sort_order'], bool):
        raise _manifest_error(path, 'category sort_order must be an integer.')
    return CategorySpec(**raw)


def _parameter_from_json(
    path: Path,
    raw: Any,
    *,
    manifest_service: str | None,
) -> ParameterSpec:
    if not isinstance(raw, dict):
        raise _manifest_error(path, 'each parameter must be a JSON object.')
    unknown = sorted(set(raw) - _PARAMETER_FIELDS)
    if unknown:
        raise _manifest_error(path, f'unknown parameter fields: {", ".join(unknown)}.')
    values = dict(raw)
    service = values.pop('service', manifest_service)
    required = {'key', 'category', 'label', 'description'}
    missing = sorted(required - set(values))
    if missing:
        raise _manifest_error(path, f'missing parameter fields: {", ".join(missing)}.')
    if not isinstance(service, str) or not service:
        raise _manifest_error(path, 'parameter service must be a non-empty string.')
    for field_name in ('key', 'category', 'label', 'description'):
        if not isinstance(values[field_name], str):
            raise _manifest_error(path, f'parameter {field_name} must be a string.')

    values.setdefault('data_type', 'string')
    values.setdefault('default_value', None)
    values.setdefault('validation_rules', {})
    values.setdefault('source', 'database')
    values.setdefault('is_secret', False)
    values.setdefault('is_required', False)
    values.setdefault('requires_restart', True)
    values.setdefault('sort_order', 0)
    if values['data_type'] not in _DATA_TYPES:
        raise _manifest_error(path, f'unsupported data_type: {values["data_type"]}.')
    if values['source'] not in _SOURCES:
        raise _manifest_error(path, f'unsupported source: {values["source"]}.')
    if not isinstance(values['validation_rules'], dict):
        raise _manifest_error(path, 'validation_rules must be a JSON object.')
    for field_name in ('is_secret', 'is_required', 'requires_restart'):
        if not isinstance(values[field_name], bool):
            raise _manifest_error(path, f'{field_name} must be a boolean.')
    if not isinstance(values['sort_order'], int) or isinstance(values['sort_order'], bool):
        raise _manifest_error(path, 'parameter sort_order must be an integer.')
    return ParameterSpec(service=service, **values)


def load_managed_catalog(
    manifest_dir: Path = MANIFEST_DIR,
) -> tuple[tuple[CategorySpec, ...], tuple[ParameterSpec, ...]]:
    paths = sorted(manifest_dir.glob('*.json'))
    if not paths:
        raise ImproperlyConfigured(f'No managed catalog manifests found in {manifest_dir}.')

    categories: dict[str, CategorySpec] = {}
    parameters: list[ParameterSpec] = []
    parameter_keys: set[str] = set()
    identities: set[tuple[str, str]] = set()
    for path in paths:
        payload = _load_json(path)
        raw_categories = payload.get('categories', [])
        raw_parameters = payload.get('parameters', [])
        if not isinstance(raw_categories, list) or not isinstance(raw_parameters, list):
            raise _manifest_error(path, 'categories and parameters must be JSON arrays.')
        for raw_category in raw_categories:
            category = _category_from_json(path, raw_category)
            existing = categories.get(category.code)
            if existing is not None and existing != category:
                raise _manifest_error(path, f'conflicting category: {category.code}.')
            categories[category.code] = category

        manifest_service = payload.get('service')
        if manifest_service is not None and (
            not isinstance(manifest_service, str) or not manifest_service
        ):
            raise _manifest_error(path, 'service must be a non-empty string.')
        for raw_parameter in raw_parameters:
            parameter = _parameter_from_json(
                path, raw_parameter, manifest_service=manifest_service
            )
            identity = (parameter.service, parameter.key)
            if identity in identities:
                raise _manifest_error(
                    path,
                    f'duplicate parameter identity: {parameter.service}/{parameter.key}.',
                )
            if parameter.key in parameter_keys:
                raise _manifest_error(
                    path,
                    f'parameter key must be globally unique: {parameter.key}.',
                )
            identities.add(identity)
            parameter_keys.add(parameter.key)
            parameters.append(parameter)

    missing_categories = sorted(
        {parameter.category for parameter in parameters} - set(categories)
    )
    if missing_categories:
        raise ImproperlyConfigured(
            'Managed catalog parameters reference unknown categories: '
            + ', '.join(missing_categories)
            + '.'
        )
    ordered_categories = tuple(sorted(categories.values(), key=lambda item: item.sort_order))
    return ordered_categories, tuple(parameters)


CATEGORIES, PARAMETERS = load_managed_catalog()
PARAMETERS_BY_KEY = {parameter.key: parameter for parameter in PARAMETERS}
_PLACEHOLDER_RE = re.compile(r'^<[^>]+>$')


def parse_env_value(spec: ParameterSpec, raw_value: str | None) -> Any:
    if raw_value is None or raw_value == '':
        raise ValidationError('Value is empty.')
    value = raw_value.strip()
    if _PLACEHOLDER_RE.fullmatch(value):
        raise ValidationError('Value is a placeholder.')
    if spec.data_type == 'integer':
        try:
            return int(value)
        except ValueError as exc:
            raise ValidationError('Value must be an integer.') from exc
    if spec.data_type == 'float':
        try:
            return float(value)
        except ValueError as exc:
            raise ValidationError('Value must be a number.') from exc
    if spec.data_type == 'boolean':
        normalized = value.lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        raise ValidationError('Value must be a boolean.')
    if spec.data_type == 'json':
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValidationError('Value must be valid JSON.') from exc
    return value
