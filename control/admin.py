from django.contrib import admin

from control.models import (
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
