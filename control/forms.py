from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from control.models import (
    API_KEY_MIN_LENGTH,
    MAIL_AGENT_PERMISSIONS,
    AccessRole,
    ApiCredential,
    MailAgentPolicy,
    SqlAccessProfile,
    generate_api_key,
)


class ApiCredentialAdminForm(forms.ModelForm):
    selected_access_roles = forms.ModelMultipleChoiceField(
        label='Access roles',
        queryset=AccessRole.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        help_text='Effective API scopes are inherited from the selected roles.',
    )
    selected_sql_profiles = forms.ModelMultipleChoiceField(
        label='SQL access profiles',
        queryset=SqlAccessProfile.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Only profiles from the credential environment can be assigned.',
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
            'selected_access_roles',
            'selected_sql_profiles',
            'is_active',
            'expires_at',
        )
        widgets = {
            'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['selected_access_roles'].queryset = AccessRole.objects.filter(
            is_active=True
        ).order_by('code')
        self.fields['selected_sql_profiles'].queryset = SqlAccessProfile.objects.filter(
            is_active=True
        ).order_by('environment', 'code')
        if self.instance.pk:
            self.initial['selected_access_roles'] = self.instance.access_roles.all()
            self.initial['selected_sql_profiles'] = self.instance.sql_profiles.all()

    def clean(self):
        cleaned_data = super().clean()
        raw_key = cleaned_data.get('raw_key')
        generate_key_requested = cleaned_data.get('generate_key', False)
        environment = cleaned_data.get('environment')
        sql_profiles = cleaned_data.get('selected_sql_profiles')

        if environment and sql_profiles:
            mismatched = [
                profile.code
                for profile in sql_profiles
                if profile.environment != environment
            ]
            if mismatched:
                self.add_error(
                    'selected_sql_profiles',
                    'Profiles belong to another environment: '
                    + ', '.join(sorted(mismatched)),
                )

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

    def _save_m2m(self):
        super()._save_m2m()
        self.instance.access_roles.set(self.cleaned_data['selected_access_roles'])
        self.instance.sql_profiles.set(
            self.cleaned_data.get('selected_sql_profiles', [])
        )

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
