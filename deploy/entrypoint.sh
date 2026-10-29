#!/usr/bin/env sh
# Entrypoint de produção: prepara o Django e só então sobe o Gunicorn.
set -e

echo ">> Aplicando migrations..."
python manage.py migrate --noinput

echo ">> Coletando arquivos estáticos..."
python manage.py collectstatic --noinput

# Garante os grupos padrão (admin, veterinario, recepcao) e cria os usuários
# iniciais definidos no ambiente (mesma lógica do build.sh do Render).
echo ">> Garantindo grupos e usuários iniciais..."
python manage.py setup_inicial

# Executa o comando passado no `command:` do docker-compose (Gunicorn).
exec "$@"
