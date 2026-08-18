import os


os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-secret-key')
os.environ.setdefault('DJANGO_CONFIG_API_KEY', 'test-service-token')
os.environ.setdefault('DJANGO_DB_HOST', '127.0.0.1')
os.environ.setdefault('DJANGO_DB_USER', 'test-user')
os.environ.setdefault('DJANGO_DB_PASSWORD', 'test-password')

from config.settings import *  # noqa: E402,F403


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
