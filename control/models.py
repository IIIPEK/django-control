from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, URLValidator
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


API_KEY_HASH_ALGORITHM = 'sha256'
API_KEY_MIN_LENGTH = 32
MAIL_AGENT_PERMISSIONS = (
    ('mail.read', 'Read mail'),
    ('drafts.create', 'Create drafts'),
    ('mail.send', 'Send mail'),
    ('mail.workflow', 'Run mail workflow'),
)
MAIL_AGENT_PERMISSION_CODES = frozenset(code for code, _label in MAIL_AGENT_PERMISSIONS)


def api_key_digest(raw_key: str) -> str:
    value = raw_key.strip()
    if len(value) < API_KEY_MIN_LENGTH:
        raise ValidationError(
            f'API keys must contain at least {API_KEY_MIN_LENGTH} characters.'
        )
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def generate_api_key() -> str:
    return f'api_{secrets.token_urlsafe(32)}'


class ApiCredential(models.Model):
    class Role(models.TextChoices):
        CLIENT = 'client', 'Client'
        AGENT = 'agent', 'Agent'
        ADMIN = 'admin', 'Administrator'

    class Scope(models.TextChoices):
        MAIL_API = 'mail.api', 'Mail API'
        SQL_QUERY = 'sql.query', 'SQL queries'
        VOICE_TRANSCRIBE = 'voice.transcribe', 'Voice transcription'
        DIARIZATION_RUN = 'diarization.run', 'Diarization'

    id = models.BigAutoField(primary_key=True)
    environment = models.CharField(
        max_length=16,
        choices=ParameterValue.Environment.choices,
        db_index=True,
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, db_index=True)
    scopes = models.JSONField(default=list)
    key_id = models.CharField(max_length=12, unique=True, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    hash_algorithm = models.CharField(
        max_length=16,
        default=API_KEY_HASH_ALGORITHM,
        editable=False,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_api_credentials',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='updated_api_credentials',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ('environment', 'name')
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                'environment',
                name='uq_api_credential_name_env_ci',
            ),
            models.CheckConstraint(
                condition=~Q(key_id=''),
                name='ck_api_credential_key_id_set',
            ),
            models.CheckConstraint(
                condition=~Q(key_hash=''),
                name='ck_api_credential_hash_set',
            ),
        ]

    def set_key(self, raw_key: str) -> None:
        digest = api_key_digest(raw_key)
        self.key_id = digest[:12]
        self.key_hash = digest
        self.hash_algorithm = API_KEY_HASH_ALGORITHM

    def matches_key(self, raw_key: str) -> bool:
        try:
            digest = api_key_digest(raw_key)
        except ValidationError:
            return False
        return secrets.compare_digest(digest, self.key_hash)

    def clean(self) -> None:
        super().clean()
        self.name = self.name.strip()
        errors: dict[str, str] = {}
        if not self.name:
            errors['name'] = 'Credential name cannot be blank.'
        if not isinstance(self.scopes, list):
            errors['scopes'] = 'Scopes must be a JSON array.'
        else:
            normalized_scopes = list(
                dict.fromkeys(
                    scope.strip()
                    for scope in self.scopes
                    if isinstance(scope, str) and scope.strip()
                )
            )
            if len(normalized_scopes) != len(self.scopes):
                errors['scopes'] = 'Scopes must be unique non-empty strings.'
            unknown_scopes = sorted(
                set(normalized_scopes) - set(self.Scope.values)
            )
            if unknown_scopes:
                errors['scopes'] = f'Unknown scopes: {", ".join(unknown_scopes)}.'
            elif not normalized_scopes:
                errors['scopes'] = 'At least one scope is required.'
            self.scopes = normalized_scopes
        if self.hash_algorithm != API_KEY_HASH_ALGORITHM:
            errors['hash_algorithm'] = 'Unsupported API key hash algorithm.'
        if not self.key_id:
            errors['key_id'] = 'API key is not configured.'
        elif re.fullmatch(r'[0-9a-f]{12}', self.key_id) is None:
            errors['key_id'] = 'Key ID must be a 12-character SHA-256 prefix.'
        if not self.key_hash:
            errors['key_hash'] = 'API key is not configured.'
        elif re.fullmatch(r'[0-9a-f]{64}', self.key_hash) is None:
            errors['key_hash'] = 'Key hash must be a hexadecimal SHA-256 digest.'
        if self.key_hash and self.key_id and not self.key_hash.startswith(self.key_id):
            errors['key_id'] = 'Key ID must match the stored hash prefix.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.name} [{self.environment}]'


class MailAgentPolicy(models.Model):
    id = models.BigAutoField(primary_key=True)
    credential = models.OneToOneField(
        ApiCredential,
        on_delete=models.CASCADE,
        related_name='mail_policy',
    )
    mailboxes = models.JSONField(default=list)
    permissions = models.JSONField(default=list)
    recipient_domains = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('credential__environment', 'credential__name')
        verbose_name = 'mail agent policy'
        verbose_name_plural = 'mail agent policies'

    @staticmethod
    def _string_list(value: Any, field_name: str, *, lower: bool) -> list[str]:
        if not isinstance(value, list):
            raise ValidationError({field_name: 'Value must be a JSON array.'})
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValidationError(
                    {field_name: 'Every item must be a non-empty string.'}
                )
            item = item.strip()
            normalized.append(item.lower() if lower else item)
        return list(dict.fromkeys(normalized))

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        try:
            self.mailboxes = self._string_list(
                self.mailboxes,
                'mailboxes',
                lower=True,
            )
            if not self.mailboxes:
                errors['mailboxes'] = 'At least one mailbox is required.'
            else:
                validator = EmailValidator()
                for mailbox in self.mailboxes:
                    validator(mailbox)
        except ValidationError as exc:
            errors['mailboxes'] = '; '.join(exc.messages)

        try:
            self.permissions = self._string_list(
                self.permissions,
                'permissions',
                lower=False,
            )
            unknown = sorted(set(self.permissions) - MAIL_AGENT_PERMISSION_CODES)
            if not self.permissions:
                errors['permissions'] = 'At least one permission is required.'
            elif unknown:
                errors['permissions'] = f'Unknown permissions: {", ".join(unknown)}.'
        except ValidationError as exc:
            errors['permissions'] = '; '.join(exc.messages)

        try:
            domains = self._string_list(
                self.recipient_domains,
                'recipient_domains',
                lower=True,
            )
            self.recipient_domains = [domain.removeprefix('@') for domain in domains]
            invalid_domains = [
                domain
                for domain in self.recipient_domains
                if domain != '*'
                and re.fullmatch(
                    r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
                    r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',
                    domain,
                )
                is None
            ]
            if invalid_domains:
                errors['recipient_domains'] = (
                    f'Invalid recipient domains: {", ".join(invalid_domains)}.'
                )
        except ValidationError as exc:
            errors['recipient_domains'] = '; '.join(exc.messages)

        if self.credential_id:
            if self.credential.role != ApiCredential.Role.AGENT:
                errors['credential'] = (
                    'Mail policies can only be assigned to agent credentials.'
                )
            elif ApiCredential.Scope.MAIL_API not in self.credential.scopes:
                errors['credential'] = 'Mail policies require the mail.api scope.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'Mail policy: {self.credential}'


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
