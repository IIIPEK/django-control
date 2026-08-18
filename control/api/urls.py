from django.urls import path

from control.api.views import credentials, effective_config, mail_credentials


app_name = 'control_api'

urlpatterns = [
    path(
        'config/<str:environment>/',
        effective_config,
        name='effective-config',
    ),
    path(
        'credentials/<str:environment>/',
        credentials,
        name='credentials',
    ),
    path(
        'credentials/mail/<str:environment>/',
        mail_credentials,
        name='mail-credentials',
    ),
]
