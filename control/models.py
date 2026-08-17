from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models, transaction
from django.db.models import Max, Q
from django.db.models.functions import Lower


class ParameterCategory(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ('sort_order', 'name')
        verbose_name = 'parameter category'
        verbose_name_plural = 'parameter categories'
        constraints = [
            models.UniqueConstraint(
                Lower('code'),
                name='uq_parameter_category_code_ci',
            ),
            models.CheckConstraint(
                condition=~Q(code=''),
                name='ck_parameter_category_code_set',
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.code = self.code.strip().lower()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class ParameterDefinition(models.Model):
    class DataType(models.TextChoices):
        STRING = 'string', 'String'
        INTEGER = 'integer', 'Integer'
        FLOAT = 'float', 'Float'
        BOOLEAN = 'boolean', 'Boolean'
        URL = 'url', 'URL'
        JSON = 'json', 'JSON'

    class Source(models.TextChoices):
        DATABASE = 'database', 'Database'
        ENVIRONMENT = 'env', 'Environment'
        DEFAULT = 'default', 'Default'

    id = models.BigAutoField(primary_key=True)
    category = models.ForeignKey(
        ParameterCategory,
        on_delete=models.PROTECT,
        related_name='definitions',
    )
    service = models.SlugField(max_length=64, db_index=True)
    key = models.CharField(max_length=128, db_index=True)
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    data_type = models.CharField(max_length=16, choices=DataType.choices)
    default_value = models.JSONField(null=True, blank=True)
    validation_rules = models.JSONField(default=dict, blank=True)
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.DATABASE,
    )
    is_secret = models.BooleanField(default=False)
    is_required = models.BooleanField(default=False)
    requires_restart = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('category__sort_order', 'sort_order', 'service', 'key')
        constraints = [
            models.UniqueConstraint(
                Lower('service'),
                Lower('key'),
                name='uq_parameter_definition_service_key_ci',
            ),
            models.CheckConstraint(
                condition=~Q(service=''),
                name='ck_parameter_definition_service_set',
            ),
            models.CheckConstraint(
                condition=~Q(key=''),
                name='ck_parameter_definition_key_set',
            ),
            models.CheckConstraint(
                condition=Q(is_secret=False) | Q(source='env'),
                name='ck_parameter_secret_uses_env',
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.service = self.service.strip().lower()
        self.key = self.key.strip().upper()

        errors: dict[str, str] = {}
        if not isinstance(self.validation_rules, dict):
            errors['validation_rules'] = 'Validation rules must be a JSON object.'
        if self.is_secret and self.source != self.Source.ENVIRONMENT:
            errors['source'] = 'Secret parameters must use the environment source.'
        if self.is_secret and self.default_value is not None:
            errors['default_value'] = 'Secret parameters cannot have a default value.'
        if self.source == self.Source.DEFAULT and self.default_value is None:
            errors['default_value'] = 'Default-sourced parameters must have a default value.'
        if self.default_value is not None:
            try:
                validate_parameter_value(
                    self.default_value,
                    self.data_type,
                    self.validation_rules if isinstance(self.validation_rules, dict) else {},
                )
            except ValidationError as exc:
                errors['default_value'] = '; '.join(exc.messages)
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.service}: {self.key}'


class ParameterValue(models.Model):
    class Environment(models.TextChoices):
        DEVELOPMENT = 'development', 'Development'
        STAGING = 'staging', 'Staging'
        PRODUCTION = 'production', 'Production'

    id = models.BigAutoField(primary_key=True)
    definition = models.ForeignKey(
        ParameterDefinition,
        on_delete=models.PROTECT,
        related_name='values',
    )
    environment = models.CharField(
        max_length=16,
        choices=Environment.choices,
        db_index=True,
    )
    value = models.JSONField()
    is_active = models.BooleanField(default=True, db_index=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='updated_parameter_values',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ('definition__service', 'definition__key', 'environment')
        constraints = [
            models.UniqueConstraint(
                fields=('definition', 'environment'),
                name='uq_parameter_value_definition_env',
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.definition.source != ParameterDefinition.Source.DATABASE:
            errors['definition'] = 'Only database-sourced parameters can have stored values.'
        if self.definition.is_secret:
            errors['definition'] = 'Secret parameters cannot have stored values.'
        try:
            validate_parameter_value(
                self.value,
                self.definition.data_type,
                self.definition.validation_rules,
            )
        except ValidationError as exc:
            errors['value'] = '; '.join(exc.messages)
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        using = kwargs.get('using') or self._state.db or 'default'

        with transaction.atomic(using=using):
            previous_value: Any = None
            change_comment = ''
            record_change = self._state.adding
            if not self._state.adding:
                previous = (
                    type(self).objects.using(using).select_for_update().get(pk=self.pk)
                )
                identity_errors: dict[str, str] = {}
                if previous.definition_id != self.definition_id:
                    identity_errors['definition'] = 'Definition cannot be changed after creation.'
                if previous.environment != self.environment:
                    identity_errors['environment'] = 'Environment cannot be changed after creation.'
                if identity_errors:
                    raise ValidationError(identity_errors)
                previous_value = previous.value
                record_change = previous.value != self.value or previous.is_active != self.is_active
                if previous.is_active != self.is_active:
                    change_comment = (
                        f'Activation changed from {previous.is_active} to {self.is_active}.'
                    )

            super().save(*args, **kwargs)

            if record_change:
                last_revision = (
                    ParameterChange.objects.using(using)
                    .filter(
                        definition=self.definition,
                        environment=self.environment,
                    )
                    .aggregate(value=Max('revision'))['value']
                    or 0
                )
                ParameterChange.objects.using(using).create(
                    definition=self.definition,
                    environment=self.environment,
                    revision=last_revision + 1,
                    old_value=previous_value,
                    new_value=self.value,
                    changed_by=self.updated_by,
                    comment=change_comment,
                )

    def __str__(self) -> str:
        return f'{self.definition} [{self.environment}]'


class ParameterChange(models.Model):
    id = models.BigAutoField(primary_key=True)
    definition = models.ForeignKey(
        ParameterDefinition,
        on_delete=models.PROTECT,
        related_name='changes',
    )
    environment = models.CharField(
        max_length=16,
        choices=ParameterValue.Environment.choices,
        db_index=True,
    )
    revision = models.PositiveBigIntegerField()
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='parameter_changes',
    )
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ('-changed_at', '-revision')
        constraints = [
            models.UniqueConstraint(
                fields=('definition', 'environment', 'revision'),
                name='uq_parameter_change_revision',
            ),
        ]
        indexes = [
            models.Index(
                fields=('definition', 'environment', '-changed_at'),
                name='control_chg_history_idx',
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError('Parameter change history is immutable.')
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise ValidationError('Parameter change history cannot be deleted.')

    def __str__(self) -> str:
        return f'{self.definition} [{self.environment}] r{self.revision}'


def validate_parameter_value(value: Any, data_type: str, rules: dict[str, Any]) -> None:
    errors: list[str] = []

    if data_type == ParameterDefinition.DataType.STRING:
        if not isinstance(value, str):
            errors.append('Value must be a string.')
    elif data_type == ParameterDefinition.DataType.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append('Value must be an integer.')
    elif data_type == ParameterDefinition.DataType.FLOAT:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append('Value must be a number.')
    elif data_type == ParameterDefinition.DataType.BOOLEAN:
        if not isinstance(value, bool):
            errors.append('Value must be a boolean.')
    elif data_type == ParameterDefinition.DataType.URL:
        if not isinstance(value, str):
            errors.append('Value must be a URL string.')
        else:
            try:
                URLValidator()(value)
            except ValidationError:
                errors.append('Value must be a valid URL.')
    elif data_type != ParameterDefinition.DataType.JSON:
        errors.append(f'Unsupported parameter data type: {data_type}.')

    if errors:
        raise ValidationError(errors)

    allowed_rules = {'choices', 'min', 'max', 'min_length', 'max_length', 'regex'}
    unknown_rules = sorted(set(rules) - allowed_rules)
    if unknown_rules:
        errors.append(f'Unknown validation rule(s): {", ".join(unknown_rules)}.')

    choices = rules.get('choices')
    if choices is not None:
        if not isinstance(choices, list):
            errors.append('The choices validation rule must be a list.')
        elif value not in choices:
            errors.append('Value is not one of the allowed choices.')

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = rules.get('min')
        maximum = rules.get('max')
        if minimum is not None:
            if not isinstance(minimum, (int, float)) or isinstance(minimum, bool):
                errors.append('The min validation rule must be a number.')
            elif value < minimum:
                errors.append(f'Value must be greater than or equal to {minimum}.')
        if maximum is not None:
            if not isinstance(maximum, (int, float)) or isinstance(maximum, bool):
                errors.append('The max validation rule must be a number.')
            elif value > maximum:
                errors.append(f'Value must be less than or equal to {maximum}.')
    elif 'min' in rules or 'max' in rules:
        errors.append('The min and max validation rules require a numeric value.')

    if isinstance(value, (str, list, dict)):
        minimum_length = rules.get('min_length')
        maximum_length = rules.get('max_length')
        if minimum_length is not None:
            if not isinstance(minimum_length, int) or isinstance(minimum_length, bool) or minimum_length < 0:
                errors.append('The min_length validation rule must be a non-negative integer.')
            elif len(value) < minimum_length:
                errors.append(f'Value length must be at least {minimum_length}.')
        if maximum_length is not None:
            if not isinstance(maximum_length, int) or isinstance(maximum_length, bool) or maximum_length < 0:
                errors.append('The max_length validation rule must be a non-negative integer.')
            elif len(value) > maximum_length:
                errors.append(f'Value length must be at most {maximum_length}.')
    elif 'min_length' in rules or 'max_length' in rules:
        errors.append('Length validation rules require a string, list, or object value.')

    pattern = rules.get('regex')
    if pattern is not None:
        if not isinstance(pattern, str):
            errors.append('The regex validation rule must be a string.')
        elif not isinstance(value, str):
            errors.append('The regex validation rule requires a string value.')
        else:
            try:
                if re.fullmatch(pattern, value) is None:
                    errors.append('Value does not match the required pattern.')
            except re.error:
                errors.append('The regex validation rule is invalid.')

    if errors:
        raise ValidationError(errors)
