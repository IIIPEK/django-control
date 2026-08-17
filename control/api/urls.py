from django.urls import path

from control.api.views import effective_config


app_name = 'control_api'

urlpatterns = [
    path(
        'config/<str:environment>/',
        effective_config,
        name='effective-config',
    ),
]
