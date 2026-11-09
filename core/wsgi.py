"""
WSGI config for core project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.prod')

_django_application = get_wsgi_application()

# Permite publicar a aplicação sob um prefixo (ex.: /staging-api) mesmo quando
# o proxy encaminha o caminho completo, sem remover o prefixo. Só entra em ação
# quando FORCE_SCRIPT_NAME está definido; em produção (sem a variável) o
# comportamento é idêntico ao WSGI padrão.
_prefix = os.environ.get('FORCE_SCRIPT_NAME', '').rstrip('/')

if _prefix:
    def application(environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == _prefix or path.startswith(_prefix + '/'):
            environ['PATH_INFO'] = path[len(_prefix):] or '/'
            environ['SCRIPT_NAME'] = _prefix
        return _django_application(environ, start_response)
else:
    application = _django_application
