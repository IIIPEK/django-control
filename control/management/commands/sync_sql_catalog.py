from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from control.models import (
    ParameterValue,
    SqlAccessProfile,
    SqlQuery,
    SqlQueryCategory,
    SqlQueryGrant,
    SqlQueryPublication,
    SqlQueryRevision,
    SqlQueryStep,
)


DECLARED_VARIABLE_WITH_TYPE_RE = re.compile(
    r'\bCREATE\s+OR\s+REPLACE\s+VARIABLE\s+@([a-zA-Z_][a-zA-Z0-9_]*)\s+([^;]+);?',
    re.IGNORECASE,
)
VARIABLE_DEFAULT_RE = re.compile(
    r'\bSET\s+@([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*COALESCE\s*\(\s*@\1\s*,\s*(.+?)\s*\)\s*;?',
    re.IGNORECASE | re.DOTALL,
)


class Command(BaseCommand):
    help = 'Synchronize SQL registry metadata, SQL revisions, publications, and section profiles.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--registry-file',
            required=True,
            type=Path,
            help='Path to the FastAPI sql/registry.json file.',
        )
        parser.add_argument(
            '--environment',
            required=True,
            choices=[value for value, _label in ParameterValue.Environment.choices],
            help='Environment in which imported revisions are published.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and report changes, then roll the transaction back.',
        )

    def handle(self, *args, **options):
        registry_path = options['registry_file'].expanduser().resolve()
        environment = options['environment']
        dry_run = options['dry_run']
        registry = self._load_registry(registry_path)
        items = registry['queries']
        counters = {
            'categories': 0,
            'profiles': 0,
            'queries': 0,
            'revisions': 0,
            'publications': 0,
            'grants': 0,
            'steps': 0,
        }

        with transaction.atomic():
            categories = self._sync_categories(items, counters)
            profiles = self._sync_profiles(items, environment, counters)
            queries = self._sync_queries(items, categories, counters)
            self._sync_deprecations(items, queries)
            revisions = self._sync_revisions(
                items,
                queries,
                registry_path.parent,
                counters,
            )
            self._sync_publications(
                items,
                queries,
                revisions,
                environment,
                counters,
            )
            self._sync_grants(items, queries, profiles, counters)
            self._sync_steps(items, queries, counters)
            if dry_run:
                transaction.set_rollback(True)

        mode = 'DRY RUN' if dry_run else 'APPLIED'
        self.stdout.write(self.style.SUCCESS(f'SQL catalog sync: {mode}'))
        for name, created in counters.items():
            self.stdout.write(f'{name.capitalize()}: {created} created')

    @staticmethod
    def _load_registry(path: Path) -> dict:
        if not path.is_file():
            raise CommandError(f'SQL registry not found: {path}')
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise CommandError(f'Invalid SQL registry JSON: {exc}') from exc
        if not isinstance(value, dict) or not isinstance(value.get('queries'), list):
            raise CommandError('SQL registry must contain a queries list.')
        keys = [item.get('key') for item in value['queries'] if isinstance(item, dict)]
        if len(keys) != len(value['queries']) or any(not isinstance(key, str) for key in keys):
            raise CommandError('Every SQL registry entry must contain a string key.')
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise CommandError(f'Duplicate SQL query keys: {", ".join(duplicates)}')
        return value

    @staticmethod
    def _sync_categories(items, counters):
        categories = {}
        for index, section in enumerate(sorted({item['section'] for item in items})):
            category, created = SqlQueryCategory.objects.update_or_create(
                code=section,
                defaults={
                    'name': section.replace('_', ' ').title(),
                    'description': f'SQL queries for {section.replace("_", " ")}.',
                    'sort_order': index * 10,
                    'is_active': True,
                },
            )
            categories[section] = category
            counters['categories'] += int(created)
        return categories

    @staticmethod
    def _sync_profiles(items, environment, counters):
        profiles = {}
        for section in sorted({item['section'] for item in items}):
            profile, created = SqlAccessProfile.objects.update_or_create(
                environment=environment,
                code=section,
                defaults={
                    'name': section.replace('_', ' ').title(),
                    'description': f'Execute published {section.replace("_", " ")} SQL queries.',
                    'is_active': True,
                },
            )
            profiles[section] = profile
            counters['profiles'] += int(created)
        return profiles

    @staticmethod
    def _sync_queries(items, categories, counters):
        queries = {}
        for item in items:
            kind = (
                SqlQuery.Kind.MULTI_STEP
                if item.get('status') == 'multi_step'
                else SqlQuery.Kind.SINGLE
            )
            query, created = SqlQuery.objects.update_or_create(
                key=item['key'].upper(),
                defaults={
                    'category': categories[item['section']],
                    'title': item['title'],
                    'description': item.get('description') or item['title'],
                    'kind': kind,
                    'status': SqlQuery.Status.ACTIVE,
                },
            )
            queries[query.key] = query
            counters['queries'] += int(created)
        return queries

    @staticmethod
    def _sync_deprecations(items, queries):
        for item in items:
            query = queries[item['key'].upper()]
            replacement_key = item.get('deprecated_by')
            query.status = (
                SqlQuery.Status.DEPRECATED
                if item.get('status') == 'deprecated'
                else SqlQuery.Status.ACTIVE
            )
            query.deprecated_by = (
                queries.get(replacement_key.upper()) if replacement_key else None
            )
            query.save()

    @staticmethod
    def _sync_revisions(items, queries, sql_root, counters):
        revisions = {}
        for item in items:
            file_name = item.get('file')
            if not file_name:
                continue
            sql_path = (sql_root / file_name).resolve()
            if not sql_path.is_relative_to(sql_root) or not sql_path.is_file():
                raise CommandError(f'SQL file not found or outside registry directory: {file_name}')
            query = queries[item['key'].upper()]
            sql_text = sql_path.read_text(encoding='utf-8')
            candidate = SqlQueryRevision(
                query=query,
                sql_text=sql_text,
                parameters=Command._parameter_schema(
                    sql_text,
                    item.get('params') or {},
                ),
                result_description=item.get('result_description') or item['title'],
                comment='Imported from FastAPI SQL registry.',
            )
            candidate.clean()
            revision = query.revisions.filter(checksum=candidate.checksum).first()
            if revision is None:
                candidate.save()
                revision = candidate
                counters['revisions'] += 1
            revisions[query.key] = revision
        return revisions

    @staticmethod
    def _parameter_schema(sql_text, overrides):
        if not isinstance(overrides, dict):
            raise CommandError('SQL registry params must be a JSON object.')
        types = {
            match.group(1).lower(): ' '.join(match.group(2).strip().split()).upper()
            for match in DECLARED_VARIABLE_WITH_TYPE_RE.finditer(sql_text)
        }
        defaults = {
            match.group(1).lower(): ' '.join(match.group(2).strip().split())
            for match in VARIABLE_DEFAULT_RE.finditer(sql_text)
        }
        parameters = {}
        for name in sorted(types):
            override = overrides.get(name) or {}
            if not isinstance(override, dict):
                raise CommandError(f'Invalid SQL parameter metadata: {name}')
            parameters[name] = {
                'type': override.get('type') or types[name],
                'default': override.get('default', defaults.get(name)),
                'description': override.get('description') or 'Query parameter.',
            }
        return parameters

    @staticmethod
    def _sync_publications(items, queries, revisions, environment, counters):
        for item in items:
            if item.get('status') == 'deprecated':
                continue
            query = queries[item['key'].upper()]
            publication, created = SqlQueryPublication.objects.update_or_create(
                query=query,
                environment=environment,
                defaults={
                    'revision': revisions.get(query.key),
                    'is_enabled': True,
                    'default_limit': item.get('default_limit'),
                    'max_limit': item.get('max_limit', 100000),
                    'timeout_seconds': item.get('timeout_seconds', 120),
                },
            )
            counters['publications'] += int(created)

    @staticmethod
    def _sync_grants(items, queries, profiles, counters):
        for item in items:
            grant, created = SqlQueryGrant.objects.update_or_create(
                profile=profiles[item['section']],
                query=queries[item['key'].upper()],
                defaults={'can_execute': True},
            )
            counters['grants'] += int(created)

    @staticmethod
    def _sync_steps(items, queries, counters):
        for item in items:
            parent = queries[item['key'].upper()]
            if parent.kind != SqlQuery.Kind.MULTI_STEP:
                continue
            expected_children = []
            for position, child_key in enumerate(item.get('steps') or [], start=1):
                child = queries.get(child_key.upper())
                if child is None:
                    raise CommandError(f'Unknown SQL query step: {child_key}')
                link, created = SqlQueryStep.objects.update_or_create(
                    parent=parent,
                    position=position,
                    defaults={'child': child},
                )
                expected_children.append(child.pk)
                counters['steps'] += int(created)
            parent.step_links.exclude(child_id__in=expected_children).delete()
