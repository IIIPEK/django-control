from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import reverse

from control.forms import ApiCredentialAdminForm, MailAgentPolicyAdminForm
from control.models import (
    ApiCredential,
    MailAgentPolicy,
    ParameterCategory,
    ParameterChange,
    ParameterDefinition,
    ParameterValue,
)


@admin.register(ParameterCategory)
class ParameterCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'sort_order', 'is_active')
    list_filter = ('is_active',)
    list_editable = ('sort_order', 'is_active')
    search_fields = ('code', 'name', 'description')
    ordering = ('sort_order', 'name')


@admin.register(ParameterDefinition)
class ParameterDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        'key',
        'service',
        'category',
        'data_type',
        'source',
        'is_secret',
        'is_active',
    )
    list_filter = (
        'service',
        'category',
        'data_type',
        'source',
        'is_secret',
        'requires_restart',
        'is_active',
    )
    search_fields = ('key', 'label', 'description', 'service')
    autocomplete_fields = ('category',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('category__sort_order', 'sort_order', 'service', 'key')


@admin.register(ParameterValue)
class ParameterValueAdmin(admin.ModelAdmin):
    list_display = (
        'definition',
        'environment',
        'is_active',
        'updated_by',
        'updated_at',
    )
    list_filter = ('environment', 'is_active', 'definition__service')
    search_fields = ('definition__key', 'definition__label', 'definition__service')
    autocomplete_fields = ('definition', 'updated_by')
    readonly_fields = ('created_at', 'updated_at', 'updated_by')
    ordering = ('definition__service', 'definition__key', 'environment')

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.extend(('definition', 'environment'))
        return fields

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ParameterChange)
class ParameterChangeAdmin(admin.ModelAdmin):
    list_display = (
        'definition',
        'environment',
        'revision',
        'changed_by',
        'changed_at',
    )
    list_filter = ('environment', 'definition__service', 'changed_at')
    search_fields = ('definition__key', 'definition__label', 'definition__service')
    readonly_fields = (
        'definition',
        'environment',
        'revision',
        'old_value',
        'new_value',
        'changed_by',
        'changed_at',
        'comment',
    )
    ordering = ('-changed_at', '-revision')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class MailAgentPolicyInline(admin.StackedInline):
    model = MailAgentPolicy
    form = MailAgentPolicyAdminForm
    extra = 1
    max_num = 1
    verbose_name = 'Mail agent policy'
    verbose_name_plural = 'Mail agent policy (agent credentials only)'


@admin.register(ApiCredential)
class ApiCredentialAdmin(admin.ModelAdmin):
    form = ApiCredentialAdminForm
    inlines = (MailAgentPolicyInline,)
    list_display = (
        'name',
        'environment',
        'role',
        'scope_list',
        'key_id',
        'is_active',
        'expires_at',
        'updated_at',
    )
    list_filter = ('environment', 'role', 'is_active')
    search_fields = ('name', 'key_id', 'description')
    ordering = ('environment', 'name')
    readonly_fields = (
        'key_id',
        'hash_algorithm',
        'created_by',
        'updated_by',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'environment',
                    'name',
                    'description',
                    'role',
                    'scopes',
                    'is_active',
                    'expires_at',
                )
            },
        ),
        (
            'API key',
            {
                'fields': (
                    'raw_key',
                    'generate_key',
                    'key_id',
                    'hash_algorithm',
                ),
                'description': (
                    'The plaintext key is never stored. Entering a new key on '
                    'an existing credential rotates it.'
                ),
            },
        ),
        (
            'Audit',
            {
                'fields': (
                    'created_by',
                    'updated_by',
                    'created_at',
                    'updated_at',
                ),
                'classes': ('collapse',),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description='Scopes')
    def scope_list(self, obj):
        return ', '.join(obj.scopes)

    def response_add(self, request, obj, post_url_continue=None):
        if getattr(obj, '_generated_raw_key', None):
            return self._generated_key_response(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if getattr(obj, '_generated_raw_key', None):
            return self._generated_key_response(request, obj)
        return super().response_change(request, obj)

    def _generated_key_response(self, request, obj):
        context = {
            **self.admin_site.each_context(request),
            'title': 'API key generated',
            'opts': self.model._meta,
            'credential': obj,
            'raw_key': obj._generated_raw_key,
            'continue_url': reverse(
                'admin:control_apicredential_change',
                args=(obj.pk,),
            ),
        }
        return TemplateResponse(
            request,
            'admin/control/apicredential/key_created.html',
            context,
        )
