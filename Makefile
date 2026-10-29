.PHONY: build up down restart logs migrate migrations createsuperuser shell test \
	lint format psql reset-db prod-build prod-up prod-down prod-logs prod-migrate \
	prod-superuser prod-setup



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

migrations:
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

# ---- Produção (docker-compose.prod.yml) ----
prod-build:
	docker compose -f docker-compose.prod.yml build

prod-up:
	docker compose -f docker-compose.prod.yml up -d

prod-down:
	docker compose -f docker-compose.prod.yml down

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f

prod-migrate:
	docker compose -f docker-compose.prod.yml exec web python manage.py migrate

prod-superuser:
	docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

prod-setup:
	docker compose -f docker-compose.prod.yml exec web python manage.py setup_inicial