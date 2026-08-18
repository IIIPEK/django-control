from __future__ import annotations

import hashlib
import json
from typing import Iterable

from control.models import ApiCredential


def build_credentials(credentials: Iterable[ApiCredential]) -> dict:
    values: list[dict] = []
    for credential in credentials:
        policy = getattr(credential, 'mail_policy', None)
        values.append(
            {
                'key_id': credential.key_id,
                'key_hash': credential.key_hash,
                'hash_algorithm': credential.hash_algorithm,
                'name': credential.name,
                'role': credential.role,
                'roles': _access_role_codes(credential),
                'scopes': _effective_scope_codes(credential),
                'sql_profiles': _sql_profile_codes(credential),
                'mailboxes': list(policy.mailboxes) if policy else [],
                'permissions': list(policy.permissions) if policy else [],
                'recipient_domains': (
                    list(policy.recipient_domains) if policy else []
                ),
                'expires_at': (
                    credential.expires_at.isoformat()
                    if credential.expires_at is not None
                    else None
                ),
            }
        )

    values.sort(key=lambda item: item['key_id'])
    canonical = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return {
        'schema_version': 2,
        'credentials': values,
        'version': hashlib.sha256(canonical).hexdigest(),
    }


build_mail_credentials = build_credentials


def _effective_scope_codes(credential: ApiCredential) -> list[str]:
    method = getattr(credential, 'effective_scope_codes', None)
    if callable(method):
        return method()
    return sorted(set(getattr(credential, 'scopes', [])))


def _access_role_codes(credential: ApiCredential) -> list[str]:
    method = getattr(credential, 'access_role_codes', None)
    if callable(method):
        return method()
    return list(getattr(credential, 'roles', []))


def _sql_profile_codes(credential: ApiCredential) -> list[str]:
    method = getattr(credential, 'sql_profile_codes', None)
    if callable(method):
        return method()
    return list(getattr(credential, 'sql_profiles', []))
