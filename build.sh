#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
username = __import__('os').environ.get('DJANGO_SUPERUSER_USERNAME', '')
password = __import__('os').environ.get('DJANGO_SUPERUSER_PASSWORD', '')
email = __import__('os').environ.get('DJANGO_SUPERUSER_EMAIL', '')
if username and not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print('Superuser criado')
"