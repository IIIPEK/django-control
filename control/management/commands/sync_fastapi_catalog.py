from __future__ import annotations

from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from dotenv import dotenv_values

from control.catalogs.fastapi import (
    CATEGORIES,
    PARAMETERS,
    PARAMETERS_BY_KEY,
    parse_env_value,
)
from control.models import ParameterCategory, ParameterDefinition, ParameterValue


class Command(BaseCommand):
    help = 'Synchronize the FastAPI parameter catalog and import non-secret values.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--env-file',
            required=True,
            type=Path,
            help='Path to the source FastAPI env file.',
        )
        parser.add_argument(
            '--environment',
            required=True,
            choices=[value for value, _label in ParameterValue.Environment.choices],
            help='Target environment for imported values.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and report changes, then roll the transaction back.',
        )

    def handle(self, *args, **options):
        env_path: Path = options['env_file'].expanduser().resolve()
        environment: str = options['environment']
        dry_run: bool = options['dry_run']

        if not env_path.is_file():
            raise CommandError(f'Env file not found: {env_path}')

        raw_values = dotenv_values(env_path, interpolate=False)
        category_created = 0
        definition_created = 0
        values_created = 0
        values_updated = 0
        values_unchanged = 0
        skipped_env_values: list[str] = []
        skipped_invalid_values: list[str] = []

        with transaction.atomic():
            categories: dict[str, ParameterCategory] = {}
            for category_spec in CATEGORIES:
                category, created = ParameterCategory.objects.update_or_create(
                    code=category_spec.code,
                    defaults={
                        'name': category_spec.name,
                        'description': category_spec.description,
                        'sort_order': category_spec.sort_order,
                        'is_active': True,
                    },
                )
                categories[category_spec.code] = category
                category_created += int(created)

            definitions: dict[str, ParameterDefinition] = {}
            for spec in PARAMETERS:
                definition, created = ParameterDefinition.objects.update_or_create(
                    service=spec.service,
                    key=spec.key,
                    defaults={
                        'category': categories[spec.category],
                        'label': spec.label,
                        'description': spec.description,
                        'data_type': spec.data_type,
                        'default_value': spec.default_value,
                        'validation_rules': spec.validation_rules,
                        'source': spec.source,
                        'is_secret': spec.is_secret,
                        'is_required': spec.is_required,
                        'requires_restart': spec.requires_restart,
                        'is_active': True,
                        'sort_order': spec.sort_order,
                    },
                )
                definitions[spec.key] = definition
                definition_created += int(created)

            for key, raw_value in raw_values.items():
                spec = PARAMETERS_BY_KEY.get(key)
                if spec is None:
                    continue
                if spec.source != ParameterDefinition.Source.DATABASE or spec.is_secret:
                    skipped_env_values.append(key)
                    continue
                try:
                    value = parse_env_value(spec, raw_value)
                except ValidationError:
                    skipped_invalid_values.append(key)
                    continue

                definition = definitions[key]
                try:
                    current = ParameterValue.objects.get(
                        definition=definition,
                        environment=environment,
                    )
                except ParameterValue.DoesNotExist:
                    ParameterValue.objects.create(
                        definition=definition,
                        environment=environment,
                        value=value,
                    )
                    values_created += 1
                else:
                    if current.value == value and current.is_active:
                        values_unchanged += 1
                    else:
                        current.value = value
                        current.is_active = True
                        current.save()
                        values_updated += 1

            if dry_run:
                transaction.set_rollback(True)

        unknown_keys = sorted(set(raw_values) - set(PARAMETERS_BY_KEY))
        mode = 'DRY RUN' if dry_run else 'APPLIED'
        self.stdout.write(self.style.SUCCESS(f'FastAPI catalog sync: {mode}'))
        self.stdout.write(
            f'Categories: {len(CATEGORIES)} synchronized, {category_created} new'
        )
        self.stdout.write(
            f'Definitions: {len(PARAMETERS)} synchronized, {definition_created} new'
        )
        self.stdout.write(
            'Values: '
            f'{values_created} created, {values_updated} updated, '
            f'{values_unchanged} unchanged'
        )
        self._write_key_list(
            'Env/bootstrap/secret values intentionally not imported',
            sorted(skipped_env_values),
        )
        self._write_key_list(
            'Empty, placeholder, or invalid values not imported',
            sorted(skipped_invalid_values),
        )
        self._write_key_list(
            'Keys not used by the current FastAPI configuration code',
            unknown_keys,
        )

    def _write_key_list(self, title: str, keys: list[str]) -> None:
        if not keys:
            return
        self.stdout.write(f'{title} ({len(keys)}):')
        for key in keys:
            self.stdout.write(f'  - {key}')
