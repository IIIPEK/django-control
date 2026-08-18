from __future__ import annotations

import hashlib
import json
from typing import Iterable

from control.models import SqlQuery, SqlQueryPublication


def build_sql_catalog(
    publications: Iterable[SqlQueryPublication],
    *,
    environment: str,
) -> dict:
    values: list[dict] = []
    for publication in publications:
        query = publication.query
        revision = publication.revision
        profiles = sorted(
            grant.profile.code
            for grant in query.profile_grants.all()
            if grant.can_execute
            and grant.profile.is_active
            and grant.profile.environment == environment
        )
        steps = [
            link.child.key
            for link in sorted(query.step_links.all(), key=lambda item: item.position)
        ]
        values.append(
            {
                'key': query.key,
                'title': query.title,
                'description': query.description,
                'category': query.category.code,
                'kind': query.kind,
                'status': query.status,
                'deprecated_by': (
                    query.deprecated_by.key if query.deprecated_by_id else None
                ),
                'revision': revision.revision if revision else None,
                'checksum': revision.checksum if revision else None,
                'sql': revision.sql_text if revision else None,
                'parameters': revision.parameters if revision else {},
                'result_description': (
                    revision.result_description if revision else ''
                ),
                'profiles': profiles,
                'steps': steps,
                'default_limit': publication.default_limit,
                'max_limit': publication.max_limit,
                'timeout_seconds': publication.timeout_seconds,
            }
        )

    values.sort(key=lambda item: item['key'])
    canonical = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return {
        'schema_version': 1,
        'environment': environment,
        'queries': values,
        'version': hashlib.sha256(canonical).hexdigest(),
    }
