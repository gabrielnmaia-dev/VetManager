build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

migrate:
	docker compose exec web python manage.py migrate

makemigrations:
	docker compose exec web python manage.py makemigrations

createsuperuser:
	docker compose exec web python manage.py createsuperuser

shell:
	docker compose exec web python manage.py shell

test:
	docker compose exec web python manage.py test

lint:
	docker compose exec web ruff check .

format:
	docker compose exec web black . && docker compose exec web isort .

psql:
	docker compose exec db psql -U vetmanager_user -d vetmanager

reset-db:
	docker compose down -v && docker compose up -d db