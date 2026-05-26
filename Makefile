up:
docker compose up --build

down:
docker compose down

logs:
docker compose logs -f

migrations:
docker compose exec api pytohn manage.py makemigrations

migrate:
docker compose exec api python manage.py migrate

shell:
docker compose exec api python manage.py shell

creatsuperuser:
docker compose exec api python manage.py createsuperuser

app:
docker compose exec api python manage.py startapp $(name)