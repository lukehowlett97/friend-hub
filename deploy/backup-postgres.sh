#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/friend-hub/app}
BACKUP_DIR=${BACKUP_DIR:-/opt/friend-hub/backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
COMPOSE_FILE=${COMPOSE_FILE:-deploy/docker-compose.prod.yml}
COMPOSE_ENV_FILE=${COMPOSE_ENV_FILE:-.env}

if [ ! -f "$APP_DIR/$COMPOSE_ENV_FILE" ]; then
  echo "No app env found; skipping backup"
  exit 0
fi

mkdir -p "$BACKUP_DIR"

cd "$APP_DIR"

timestamp=$(date +%F)
backup_path="$BACKUP_DIR/friend-hub-$timestamp.sql.gz"

docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$backup_path"

find "$BACKUP_DIR" -type f -name "friend-hub-*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
