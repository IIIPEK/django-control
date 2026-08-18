from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from control.models import (
    API_KEY_MIN_LENGTH,
    MAIL_AGENT_PERMISSIONS,
    ApiCredential,
    MailAgentPolicy,
    generate_api_key,
)


class ApiCredentialAdminForm(forms.ModelForm):
    scopes = forms.MultipleChoiceField(
        choices=ApiCredential.Scope.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select every FastAPI capability allowed for this key.',
    )
    raw_key = forms.CharField(
        label='API key',
        required=False,
        strip=True,
        min_length=API_KEY_MIN_LENGTH,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text=(
            'Enter an existing key to hash it. Leave blank and select '
            '“Generate a new key” to create one automatically. On an existing '
            'credential, leave both fields blank to keep the current key.'
        ),
    )
    generate_key = forms.BooleanField(
        label='Generate a new key',
        required=False,
        help_text='The generated key is shown once immediately after saving.',
    )

    class Meta:
        model = ApiCredential
        fields = (
            'environment',
            'name',
            'description',
            'role',
            'scopes',
            'is_active',
            'expires_at',
        )
        widgets = {
            'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['scopes'] = self.instance.scopes

    def clean_scopes(self) -> list[str]:
        return list(self.cleaned_data['scopes'])

    def clean(self):
        cleaned_data = super().clean()
        raw_key = cleaned_data.get('raw_key')
        generate_key_requested = cleaned_data.get('generate_key', False)

        if raw_key and generate_key_requested:
            raise ValidationError('Enter an API key or generate one, not both.')
        if self.instance._state.adding and not raw_key and not generate_key_requested:
            raise ValidationError('Enter an API key or select automatic generation.')
        if generate_key_requested:
            raw_key = generate_api_key()
            self.instance._generated_raw_key = raw_key
        if raw_key:
            self.instance.set_key(raw_key)
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class MailAgentPolicyAdminForm(forms.ModelForm):
    mailboxes = forms.CharField(
        label='Allowed mailboxes',
        widget=forms.Textarea(attrs={'rows': 4}),
        help_text='One mailbox address per line.',
    )
    permissions = forms.MultipleChoiceField(
        choices=MAIL_AGENT_PERMISSIONS,
        widget=forms.CheckboxSelectMultiple,
    )
    recipient_domains = forms.CharField(
        label='Allowed recipient domains',
        required=False,
        widget=forms.Textarea(attrs={'rows': 4}),
        help_text='One domain per line. Use * to allow every recipient domain.',
    )

    class Meta:
        model = MailAgentPolicy
        fields = ('mailboxes', 'permissions', 'recipient_domains')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['mailboxes'] = '\n'.join(self.instance.mailboxes)
            self.initial['permissions'] = self.instance.permissions
            self.initial['recipient_domains'] = '\n'.join(
                self.instance.recipient_domains
            )

    @staticmethod
    def _lines(value: str) -> list[str]:
        return [line.strip() for line in value.splitlines() if line.strip()]

    def clean_mailboxes(self) -> list[str]:
        return self._lines(self.cleaned_data['mailboxes'])

    def clean_permissions(self) -> list[str]:
        return list(self.cleaned_data['permissions'])

    def clean_recipient_domains(self) -> list[str]:
        return self._lines(self.cleaned_data.get('recipient_domains', ''))
