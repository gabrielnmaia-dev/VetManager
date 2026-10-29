#!/usr/bin/env bash
# =========================================================
# VetManager - Restauração de dump no banco de PRODUÇÃO
# =========================================================
# PERIGOSO: sobrescreve os dados atuais do banco de produção.
# Antes de restaurar, gera um dump de segurança do estado atual
# (pre_migration_*.sql.gz) e para o container web.
#
# Uso:
#   deploy/restore_db.sh backups/vetmanager_20261029_114242.sql.gz
# =========================================================
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
DOCKER="${DOCKER:-/usr/bin/docker}"
ARQ="${1:-}"

if [ -z "$ARQ" ] || [ ! -f "$ARQ" ]; then
  echo "uso: $0 <arquivo.sql.gz>" >&2
  exit 2
fi
command -v gzip >/dev/null || { echo "gzip não encontrado" >&2; exit 1; }
gzip -t "$ARQ" || { echo "arquivo inválido/corrompido: $ARQ" >&2; exit 1; }

echo "=================================================================="
echo " ATENÇÃO: isto vai SOBRESCREVER o banco de PRODUÇÃO com:"
echo "   $ARQ"
echo "=================================================================="
printf "Digite 'CONFIRMAR' para continuar: "
read -r ans
[ "$ans" = "CONFIRMAR" ] || { echo "abortado"; exit 1; }

cd "$PROJECT_DIR"

echo ">> Gerando backup de segurança do estado atual..."
./deploy/backup_db.sh --pre-migration

echo ">> Parando o container web (evita conexões durante o restore)..."
"$DOCKER" compose -f "$COMPOSE_FILE" stop web >/dev/null

restore_ok=0
if gunzip -c "$ARQ" | "$DOCKER" compose -f "$COMPOSE_FILE" exec -T db \
      sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; then
  restore_ok=1
fi

echo ">> Subindo o container web..."
"$DOCKER" compose -f "$COMPOSE_FILE" up -d web >/dev/null

if [ "$restore_ok" -ne 1 ]; then
  echo "ERRO: restore falhou. O backup de segurança está em $PROJECT_DIR/backups" >&2
  exit 1
fi

echo ">> Restore concluído com sucesso."
