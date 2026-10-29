.PHONY: build up down restart logs migrate migrations createsuperuser shell test \
	lint format psql reset-db prod-build prod-up prod-down prod-logs prod-migrate \
	prod-superuser prod-setup prod-backup prod-restore



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
	@echo "ATENÇÃO: este alvo APAGA todos os dados do ambiente de DESENVOLVIMENTO"
	@echo "(projeto 'vetmanager-dev'). A produção ('vetmanager') NÃO é afetada."
	@printf "Digite 'APAGAR' para continuar: " && read ans && [ "$$ans" = "APAGAR" ] || (echo "abortado"; exit 1)
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

# Backup manual do banco de produção (também roda diariamente via cron).
prod-backup:
	./deploy/backup_db.sh

# Restaura um dump no banco de produção. PERIGOSO: sobrescreve os dados atuais.
# Uso: make prod-restore FILE=backups/vetmanager_AAAAMMDD_HHMMSS.sql.gz
prod-restore:
	@test -n "$(FILE)" || (echo "informe FILE=backups/arquivo.sql.gz"; exit 1)
	./deploy/restore_db.sh "$(FILE)"