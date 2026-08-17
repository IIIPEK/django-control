from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from control.models import ParameterDefinition


def build_effective_config(
    definitions: Iterable[ParameterDefinition],
    *,
    environment: str,
    services: list[str],
) -> dict[str, Any]:
    values: dict[str, dict[str, Any]] = {service: {} for service in services}
    requires_restart: dict[str, list[str]] = {service: [] for service in services}
    missing_required: dict[str, list[str]] = {service: [] for service in services}

    for definition in definitions:
        if definition.is_secret or definition.source != ParameterDefinition.Source.DATABASE:
            continue

        stored_values = getattr(definition, 'effective_values', ())
        if stored_values:
            value = stored_values[0].value
        elif definition.default_value is not None:
            value = definition.default_value
        else:
            if definition.is_required:
                missing_required[definition.service].append(definition.key)
            continue

        values[definition.service][definition.key] = value
        if definition.requires_restart:
            requires_restart[definition.service].append(definition.key)

    for service in services:
        values[service] = dict(sorted(values[service].items()))
        requires_restart[service].sort()
        missing_required[service].sort()

    payload: dict[str, Any] = {
        'schema_version': 1,
        'environment': environment,
        'services': services,
        'values': values,
        'requires_restart': requires_restart,
        'missing_required': missing_required,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    payload['version'] = hashlib.sha256(canonical).hexdigest()
    return payload
