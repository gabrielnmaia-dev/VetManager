"""
Configuracoes locais para rodar migrations e testes sem Docker/Postgres.

Uso (na raiz do projeto):
    set -a; . ./.env; set +a
    .venv/bin/python DJANGO_SETTINGS_MODULE=core.settings.test manage.py test

Na pratica:
    DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/python manage.py test

Usa SQLite para que a suíte rode fora do container `web` (core.settings.dev
aponta para o host `db`, que só existe com o docker-compose em execução).
"""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",
    }
}

# O .env define REDIS_URL (host `redis` do docker-compose). Sem esse serviço
# localmente, o throttle estoura ConnectionError e toda request vira 500.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
