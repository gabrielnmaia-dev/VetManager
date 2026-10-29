#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Garante os grupos padrão e cria os usuários iniciais (superusuário e,
# se configurado, o usuário de recepção/atendente).
python manage.py setup_inicial