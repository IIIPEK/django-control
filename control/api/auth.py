from __future__ import annotations

import hmac
from functools import wraps

from django.conf import settings
from django.http import JsonResponse


def require_config_api_key(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        authorization = request.headers.get('Authorization', '')
        scheme, separator, token = authorization.partition(' ')
        expected = settings.CONFIG_API_KEY

        if (
            not separator
            or scheme.lower() != 'bearer'
            or not token
            or not hmac.compare_digest(token, expected)
        ):
            response = JsonResponse({'detail': 'Unauthorized.'}, status=401)
            response['WWW-Authenticate'] = 'Bearer'
            return response

        return view_func(request, *args, **kwargs)

    return wrapped
