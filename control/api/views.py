from __future__ import annotations

import re

from django.db.models import Prefetch
from django.http import HttpResponseNotModified, JsonResponse
from django.views.decorators.http import require_http_methods

from control.api.auth import require_config_api_key
from control.api.services import build_effective_config
from control.models import ParameterDefinition, ParameterValue


SERVICE_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
ENVIRONMENTS = {value for value, _label in ParameterValue.Environment.choices}


def _requested_services(raw_services: list[str]) -> list[str]:
    services = {
        service.strip().lower()
        for raw_service in raw_services
        for service in raw_service.split(',')
        if service.strip()
    }
    if not services:
        raise ValueError('At least one service query parameter is required.')
    if len(services) > 20:
        raise ValueError('No more than 20 services can be requested.')
    invalid = sorted(
        service
        for service in services
        if len(service) > 64 or SERVICE_RE.fullmatch(service) is None
    )
    if invalid:
        raise ValueError('Service names must use lowercase letters, digits, and dashes.')
    return sorted(services)


@require_config_api_key
@require_http_methods(['GET', 'HEAD'])
def effective_config(request, environment: str):
    if environment not in ENVIRONMENTS:
        return JsonResponse({'detail': 'Unknown environment.'}, status=404)

    try:
        services = _requested_services(request.GET.getlist('service'))
    except ValueError as exc:
        return JsonResponse({'detail': str(exc)}, status=400)

    effective_values = ParameterValue.objects.filter(
        environment=environment,
        is_active=True,
    ).only('definition_id', 'value')
    definitions = list(
        ParameterDefinition.objects.filter(
            service__in=services,
            source=ParameterDefinition.Source.DATABASE,
            is_secret=False,
            is_active=True,
        )
        .prefetch_related(
            Prefetch(
                'values',
                queryset=effective_values,
                to_attr='effective_values',
            )
        )
        .order_by('service', 'key')
    )

    known_services = {definition.service for definition in definitions}
    unknown_services = sorted(set(services) - known_services)
    if unknown_services:
        return JsonResponse(
            {
                'detail': 'Unknown or inactive service.',
                'services': unknown_services,
            },
            status=404,
        )

    payload = build_effective_config(
        definitions,
        environment=environment,
        services=services,
    )
    etag = f'"{payload["version"]}"'
    if request.headers.get('If-None-Match') == etag:
        response = HttpResponseNotModified()
    else:
        response = JsonResponse(payload, json_dumps_params={'ensure_ascii': False})

    response['ETag'] = etag
    response['Cache-Control'] = 'private, no-cache'
    response['Vary'] = 'Authorization'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
