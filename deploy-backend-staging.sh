#!/usr/bin/env bash
# =========================================================
# VetManager - Deploy do backend de STAGING
# =========================================================
# Faz pull da branch staging, rebuilda a imagem e sobe SOMENTE o projeto
# Docker "vetmanager-staging" (volumes e portas isolados da produção).
#
# Uso:
#   ./deploy-backend-staging.sh
#
# Variáveis opcionais:
#   STAGING_BRANCH=staging
#   STAGING_COMPOSE_FILE=docker-compose.staging.yml
#   STAGING_ENV_FILE=.env.staging
#   STAGING_APP_PORT=4001
#   STAGING_COMPOSE_PROJECT_NAME=vetmanager-staging
#   DOCKER=docker
# =========================================================
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
BRANCH="${STAGING_BRANCH:-staging}"
COMPOSE_FILE="${STAGING_COMPOSE_FILE:-docker-compose.staging.yml}"
ENV_FILE="${STAGING_ENV_FILE:-.env.staging}"
COMPOSE_PROJECT_NAME="${STAGING_COMPOSE_PROJECT_NAME:-vetmanager-staging}"
DOCKER="${DOCKER:-docker}"

cd "$PROJECT_DIR"

# Garante que o Compose resolva ${STAGING_ENV_FILE} para o arquivo escolhido.
export STAGING_ENV_FILE="$ENV_FILE"
# STAGING_APP_PORT é opcional: se vier do shell, vence o valor do env file.
if [ -n "${STAGING_APP_PORT:-}" ]; then export STAGING_APP_PORT; fi

log() { printf '\n>> %s\n' "$*"; }
die() { printf '\nERRO: %s\n' "$*" >&2; exit 1; }

command -v "$DOCKER" >/dev/null 2>&1 || die "Docker não encontrado ($DOCKER)."
[ -f "$COMPOSE_FILE" ] || die "Compose não encontrado: $COMPOSE_FILE"
[ -f "$ENV_FILE" ] || die "Env file não encontrado: $ENV_FILE (copie de $ENV_FILE.example e edite)."

# O deploy não deve rodar sobre alterações locais não commitadas.
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "Working tree sujo. Faça commit/stash antes de rodar o deploy."
fi

log "Buscando a branch $BRANCH no origin..."
git fetch origin "$BRANCH"

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git checkout "$BRANCH"
else
  log "Criando branch local $BRANCH a partir de origin/$BRANCH..."
  git checkout -b "$BRANCH" "origin/$BRANCH"
fi

log "Atualizando $BRANCH (fast-forward only)..."
git pull --ff-only origin "$BRANCH"

log "Build da imagem de staging..."
"$DOCKER" compose \
  --project-name "$COMPOSE_PROJECT_NAME" \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  build web

log "Subindo/atualizando apenas o staging (porta host: $APP_PORT)..."
"$DOCKER" compose \
  --project-name "$COMPOSE_PROJECT_NAME" \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  up -d --remove-orphans

log "Status dos containers de staging:"
"$DOCKER" compose \
  --project-name "$COMPOSE_PROJECT_NAME" \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  ps

log "Deploy de staging concluído. API publicada conforme APP_PORT do ${ENV_FILE} (default 4001)."
