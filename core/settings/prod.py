from .base import *
import os
import dj_database_url

DEBUG = False

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'

ALLOWED_HOSTS = [os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')]

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    os.environ.get('FRONTEND_URL', ''),
]

DATABASES = {
    'default': dj_database_url.parse(os.environ.get('DATABASE_URL'))
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}