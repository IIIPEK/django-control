from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import reverse

from control.forms import ApiCredentialAdminForm, MailAgentPolicyAdminForm
from control.models import (
    AccessRole,
    AccessRoleScope,
    ApiScope,
    ApiCredential,
    MailAgentPolicy,
    ParameterCategory,
    ParameterChange,
    ParameterDefinition,
    ParameterValue,
    SqlAccessProfile,
    SqlCredentialProfile,
    SqlQuery,
    SqlQueryCategory,
    SqlQueryGrant,
    SqlQueryPublication,
    SqlQueryRevision,
    SqlQueryStep,
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


class AccessRoleScopeInline(admin.TabularInline):
    model = AccessRoleScope
    extra = 1
    autocomplete_fields = ('scope',)


@admin.register(ApiScope)
class ApiScopeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'description')
    ordering = ('code',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AccessRole)
class AccessRoleAdmin(admin.ModelAdmin):
    inlines = (AccessRoleScopeInline,)
    list_display = ('code', 'name', 'scope_list', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'description', 'scopes__code')
    ordering = ('code',)
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Scopes')
    def scope_list(self, obj):
        return ', '.join(scope.code for scope in obj.scopes.all())


@admin.register(ApiCredential)
class ApiCredentialAdmin(admin.ModelAdmin):
    form = ApiCredentialAdminForm
    inlines = (MailAgentPolicyInline,)
    list_display = (
        'name',
        'environment',
        'role',
        'access_role_list',
        'scope_list',
        'sql_profile_list',
        'key_id',
        'is_active',
        'expires_at',
        'updated_at',
    )
    list_filter = ('environment', 'role', 'access_roles', 'is_active')
    search_fields = ('name', 'key_id', 'description')
    ordering = ('environment', 'name')
    readonly_fields = (
        'key_id',
        'hash_algorithm',
        'created_by',
        'updated_by',
        'created_at',
        'updated_at',
        'effective_scope_list',
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
                    'selected_access_roles',
                    'effective_scope_list',
                    'selected_sql_profiles',
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

    @admin.display(description='Access roles')
    def access_role_list(self, obj):
        return ', '.join(obj.access_role_codes())

    @admin.display(description='SQL profiles')
    def sql_profile_list(self, obj):
        return ', '.join(obj.sql_profile_codes())

    @admin.display(description='Effective scopes')
    def effective_scope_list(self, obj):
        return ', '.join(obj.scopes)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related(
                'access_roles__scopes',
                'sql_profiles',
            )
        )

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


@admin.register(SqlQueryCategory)
class SqlQueryCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'sort_order', 'is_active')
    list_filter = ('is_active',)
    list_editable = ('sort_order', 'is_active')
    search_fields = ('code', 'name', 'description')
    ordering = ('sort_order', 'name')


class SqlQueryStepInline(admin.TabularInline):
    model = SqlQueryStep
    fk_name = 'parent'
    extra = 1
    autocomplete_fields = ('child',)


@admin.register(SqlQuery)
class SqlQueryAdmin(admin.ModelAdmin):
    inlines = (SqlQueryStepInline,)
    list_display = ('key', 'title', 'category', 'kind', 'status', 'updated_at')
    list_filter = ('category', 'kind', 'status')
    search_fields = ('key', 'title', 'description')
    autocomplete_fields = ('category', 'deprecated_by')
    readonly_fields = ('created_by', 'updated_by', 'created_at', 'updated_at')
    ordering = ('key',)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SqlQueryRevision)
class SqlQueryRevisionAdmin(admin.ModelAdmin):
    list_display = ('query', 'revision', 'checksum_short', 'created_by', 'created_at')
    list_filter = ('query__category', 'created_at')
    search_fields = ('query__key', 'query__title', 'comment', 'checksum')
    autocomplete_fields = ('query',)
    readonly_fields = ('revision', 'checksum', 'created_by', 'created_at')
    ordering = ('query__key', '-revision')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description='Checksum')
    def checksum_short(self, obj):
        return obj.checksum[:12]

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.extend(('query', 'sql_text', 'parameters', 'result_description', 'comment'))
        return fields

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)


@admin.register(SqlQueryPublication)
class SqlQueryPublicationAdmin(admin.ModelAdmin):
    list_display = (
        'query',
        'environment',
        'revision',
        'is_enabled',
        'published_by',
        'published_at',
    )
    list_filter = ('environment', 'is_enabled', 'query__category')
    search_fields = ('query__key', 'query__title')
    autocomplete_fields = ('query', 'revision')
    readonly_fields = ('published_by', 'published_at')
    ordering = ('environment', 'query__key')

    def save_model(self, request, obj, form, change):
        obj.published_by = request.user
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return request.user.has_perm('control.publish_sqlquery')

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm('control.publish_sqlquery')

    def has_delete_permission(self, request, obj=None):
        return False


class SqlQueryGrantInline(admin.TabularInline):
    model = SqlQueryGrant
    extra = 1
    autocomplete_fields = ('query',)


class SqlCredentialProfileInline(admin.TabularInline):
    model = SqlCredentialProfile
    extra = 1
    autocomplete_fields = ('credential',)


@admin.register(SqlAccessProfile)
class SqlAccessProfileAdmin(admin.ModelAdmin):
    inlines = (SqlQueryGrantInline, SqlCredentialProfileInline)
    list_display = ('code', 'name', 'environment', 'is_active', 'updated_at')
    list_filter = ('environment', 'is_active')
    search_fields = ('code', 'name', 'description')
    ordering = ('environment', 'code')
    readonly_fields = ('created_at', 'updated_at')
