#!/usr/bin/env sh
# Entrypoint de produção: prepara o Django e só então sobe o Gunicorn.
set -eu

# ---------------------------------------------------------
# Backup automático antes de aplicar migrations pendentes.
# Os dumps ficam em /app/backups (bind mount -> ./backups no host)
# e são podados, mantendo apenas os KEEP_PRE_MIGRATION mais recentes.
# ---------------------------------------------------------
BACKUP_DIR="${BACKUP_DIR:-/app/backups}"
KEEP_PRE_MIGRATION="${KEEP_PRE_MIGRATION:-10}"

if [ -n "${POSTGRES_DB:-}" ] && [ -n "${POSTGRES_USER:-}" ]; then
  PENDENTES="$(python manage.py showmigrations --plan 2>/dev/null | grep -c '\[ \]' || true)"
  if [ "${PENDENTES:-0}" -gt 0 ]; then
    echo ">> ${PENDENTES} migration(s) pendente(s): gerando backup antes de aplicar..."
    mkdir -p "$BACKUP_DIR"
    ARQ="$BACKUP_DIR/pre_migration_$(date -u +%Y%m%d_%H%M%S).sql.gz"
    if PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
         --clean --if-exists --no-owner --no-privileges > "$ARQ.tmp"; then
      gzip -9 -f "$ARQ.tmp"
      echo ">> Backup pré-migration: $ARQ"
      ls -1t "$BACKUP_DIR"/pre_migration_*.sql.gz 2>/dev/null \
        | tail -n +$((KEEP_PRE_MIGRATION + 1)) \
        | while IFS= read -r f; do rm -f "$f"; done
    else
      rm -f "$ARQ.tmp"
      echo ">> ERRO: falha no backup pré-migration; abortando o start." >&2
      exit 1
    fi
  fi
fi

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
