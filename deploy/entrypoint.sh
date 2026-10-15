#!/usr/bin/env sh
# Entrypoint de produção: prepara o Django e só então sobe o Gunicorn.
set -e

echo ">> Aplicando migrations..."
python manage.py migrate --noinput

echo ">> Coletando arquivos estáticos..."
python manage.py collectstatic --noinput

# Cria o superusuário automaticamente (mesma lógica do build.sh do Render).
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo ">> Verificando superusuário '$DJANGO_SUPERUSER_USERNAME'..."
  python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ['DJANGO_SUPERUSER_USERNAME']
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(
        username,
        os.environ.get('DJANGO_SUPERUSER_EMAIL', ''),
        os.environ['DJANGO_SUPERUSER_PASSWORD'],
    )
    print('Superusuário criado:', username)
else:
    print('Superusuário já existe:', username)
"
fi

# Executa o comando passado no `command:` do docker-compose (Gunicorn).
exec "$@"
