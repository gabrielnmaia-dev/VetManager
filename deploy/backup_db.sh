#!/usr/bin/env bash
# =========================================================
# VetManager - Backup do banco de dados (producao)
# =========================================================
# Gera um dump comprimido do Postgres em ./backups (bind mount que o
# container web tambem enxerga em /app/backups).
#
# Uso:
#   deploy/backup_db.sh                  # backup diario (agendado no cron)
#   deploy/backup_db.sh --pre-migration  # dump antes de migrations
#
# Retencao: 30 dias para os dumps diarios; os 10 ultimos pre-migration.
# =========================================================
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"
KEEP_PRE_MIGRATION="${KEEP_PRE_MIGRATION:-10}"
DOCKER="${DOCKER:-/usr/bin/docker}"
LOG="$BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR"

# Serializa execucoes concorrentes (cron + deploy).
exec 9>"$BACKUP_DIR/.backup.lock"
if ! flock -n 9; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) outro backup em andamento; saindo" >>"$LOG"
  exit 1
fi

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }

KIND="vetmanager"
if [ "${1:-}" = "--pre-migration" ]; then
  KIND="pre_migration"
elif [ "$#" -gt 0 ]; then
  echo "uso: $0 [--pre-migration]" >&2
  exit 2
fi

cd "$PROJECT_DIR"
TS="$(date -u +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/${KIND}_${TS}.sql.gz"
TMP="$BACKUP_DIR/.${KIND}_${TS}.sql.gz.part"

log "iniciando dump do banco (${KIND})"
if ! "$DOCKER" compose -f "$COMPOSE_FILE" exec -T db \
      sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' \
      | gzip -9 >"$TMP"; then
  rm -f "$TMP"
  log "ERRO: falha ao gerar o dump"
  exit 1
fi

if ! gzip -t "$TMP" 2>/dev/null; then
  rm -f "$TMP"
  log "ERRO: dump corrompido"
  exit 1
fi

mv "$TMP" "$OUT"
chmod 600 "$OUT"
log "ok: $OUT ($(du -h "$OUT" | cut -f1))"

# Retencao dos dumps diarios por idade.
find "$BACKUP_DIR" -maxdepth 1 -name 'vetmanager_*.sql.gz' -mtime +"$RETAIN_DAYS" -print0 \
  | while IFS= read -r -d '' f; do rm -f "$f"; log "removido (mais de ${RETAIN_DAYS}d): $f"; done

# Mantem apenas os N ultimos pre-migration.
mapfile -t olds < <(ls -1t "$BACKUP_DIR"/pre_migration_*.sql.gz 2>/dev/null | tail -n +"$((KEEP_PRE_MIGRATION + 1))" || true)
for f in "${olds[@]:-}"; do [ -n "$f" ] && rm -f "$f" && log "removido (excesso pre-migration): $f"; done

exit 0
