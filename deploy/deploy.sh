#!/usr/bin/env bash
set -euo pipefail

SERVER=${SERVER:-}
APP_DIR=${APP_DIR:-/opt/friend-hub/app}
ENV_FILE=${ENV_FILE:-.env.prod}
COMPOSE_FILE=${COMPOSE_FILE:-deploy/docker-compose.prod.yml}
DEPLOY_REF=${DEPLOY_REF:-HEAD}
ALLOW_DIRTY=${ALLOW_DIRTY:-0}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"}
LOG_LINES=${LOG_LINES:-120}

die() {
  echo "deploy: $*" >&2
  exit 1
}

trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

env_value() {
  local key=$1
  local line value

  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    line=$(trim "$line")
    [ -z "$line" ] && continue
    [[ "$line" == \#* ]] && continue
    [[ "$line" == export[[:space:]]* ]] && line=$(trim "${line#export}")
    [[ "$line" == "$key="* ]] || continue
    value=${line#*=}
    value=$(trim "$value")
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value=${value:1:${#value}-2}
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value=${value:1:${#value}-2}
    fi
    printf '%s' "$value"
    return 0
  done < "$ENV_FILE"

  return 1
}

require_env() {
  local key=$1
  local value
  value=$(env_value "$key" || true)
  [ -n "$value" ] || die "$ENV_FILE is missing required variable $key"
}

shell_quote() {
  printf '%q' "$1"
}

[ -n "$SERVER" ] || die "SERVER is empty. Run Terraform first or pass SERVER=deploy@host."
[ -f "$ENV_FILE" ] || die "missing local env file: $ENV_FILE"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "must run from inside a Git worktree"
git rev-parse --verify "$DEPLOY_REF^{commit}" >/dev/null 2>&1 || die "DEPLOY_REF does not resolve to a commit: $DEPLOY_REF"

if [ "$ALLOW_DIRTY" != "1" ] && [ -n "$(git status --porcelain)" ]; then
  die "working tree is dirty; commit/stash changes or rerun with ALLOW_DIRTY=1"
fi

for key in DOMAIN_NAME POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB DATABASE_HOST DATABASE_PASSWORD; do
  require_env "$key"
done

domain_name=$(env_value DOMAIN_NAME || true)
database_host=$(env_value DATABASE_HOST || true)
postgres_user=$(env_value POSTGRES_USER || true)
postgres_db=$(env_value POSTGRES_DB || true)
database_user=$(env_value DATABASE_USER || true)
database_name=$(env_value DATABASE_NAME || true)

[ "$domain_name" != "temp.local" ] || die "DOMAIN_NAME must not be temp.local for production deploys"
[ "$database_host" = "postgres" ] || die "DATABASE_HOST must be postgres for Docker Compose deployment"

if [ -n "$database_user" ] && [ "$database_user" != "$postgres_user" ]; then
  die "DATABASE_USER must match POSTGRES_USER when both are set"
fi

if [ -n "$database_name" ] && [ "$database_name" != "$postgres_db" ]; then
  die "DATABASE_NAME must match POSTGRES_DB when both are set"
fi

read -r -a ssh_args <<< "$SSH_OPTS"

commit_sha=$(git rev-parse "$DEPLOY_REF")
remote_tmp="${APP_DIR}.upload.${commit_sha:0:12}.$$"
quoted_app_dir=$(shell_quote "$APP_DIR")
quoted_remote_tmp=$(shell_quote "$remote_tmp")
quoted_compose_file=$(shell_quote "$COMPOSE_FILE")
quoted_log_lines=$(shell_quote "$LOG_LINES")

echo "Deploying commit $commit_sha to $SERVER:$APP_DIR"
echo "Using env file $ENV_FILE"

ssh "${ssh_args[@]}" "$SERVER" "APP_DIR=$quoted_app_dir REMOTE_TMP=$quoted_remote_tmp bash -s" <<'REMOTE_PREP'
set -euo pipefail

deploy_user=$(id -un)
app_parent=$(dirname "$APP_DIR")

sudo install -d -m 0755 -o "$deploy_user" -g "$deploy_user" "$app_parent"
sudo install -d -m 0755 -o "$deploy_user" -g "$deploy_user" "$REMOTE_TMP"
sudo chown -R "$deploy_user:$deploy_user" "$REMOTE_TMP"

command -v docker >/dev/null 2>&1 || {
  echo "remote docker is not installed" >&2
  exit 1
}

docker compose version >/dev/null 2>&1 || {
  echo "remote docker compose plugin is not installed" >&2
  exit 1
}
REMOTE_PREP

git archive "$DEPLOY_REF" | ssh "${ssh_args[@]}" "$SERVER" "tar -xf - -C $quoted_remote_tmp"
scp "${ssh_args[@]}" "$ENV_FILE" "$SERVER:$remote_tmp/.env"

ssh "${ssh_args[@]}" "$SERVER" "APP_DIR=$quoted_app_dir REMOTE_TMP=$quoted_remote_tmp COMPOSE_FILE=$quoted_compose_file LOG_LINES=$quoted_log_lines bash -s" <<'REMOTE_DEPLOY'
set -euo pipefail

deploy_user=$(id -un)

for path in deploy/docker-compose.prod.yml backend frontend; do
  [ -e "$REMOTE_TMP/$path" ] || {
    echo "archive missing required path: $path" >&2
    exit 1
  }
done

install -m 0600 "$REMOTE_TMP/.env" "$REMOTE_TMP/.env.tmp"
mv "$REMOTE_TMP/.env.tmp" "$REMOTE_TMP/.env"
sudo chown -R "$deploy_user:$deploy_user" "$REMOTE_TMP"

if [ -e "$APP_DIR" ]; then
  [ -d "$APP_DIR" ] || {
    echo "$APP_DIR exists but is not a directory" >&2
    exit 1
  }

  owner=$(stat -c '%U:%G' "$APP_DIR")
  expected="$deploy_user:$deploy_user"
  [ "$owner" = "$expected" ] || {
    echo "$APP_DIR is owned by $owner, expected $expected" >&2
    exit 1
  }
fi

rm -rf "${APP_DIR}.previous"
if [ -d "$APP_DIR" ]; then
  mv "$APP_DIR" "${APP_DIR}.previous"
fi
mv "$REMOTE_TMP" "$APP_DIR"
rm -rf "${APP_DIR}.previous"

cd "$APP_DIR"
docker compose --env-file .env -f "$COMPOSE_FILE" up -d --build

run_sql_migration() {
  local migration=$1
  local path="backend/migrations/$migration"

  [ -f "$path" ] || {
    echo "migration file missing: $path" >&2
    exit 1
  }

  echo "Running migration: $migration"
  docker compose --env-file .env -f "$COMPOSE_FILE" exec -T postgres sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$path"
}

run_sql_migration "037_add_notification_preferences.sql"
run_sql_migration "041_backfill_imported_identities_from_external.sql"
run_sql_migration "044_enable_pgvector_photo_embeddings.sql"
run_sql_migration "045_platform_owner_room_admins.sql"
run_sql_migration "048_add_chat_read_state.sql"
run_sql_migration "049_add_memory_message_range.sql"
run_sql_migration "052_add_chat_embeddings.sql"
run_sql_migration "061_add_public_demo_room.sql"
run_sql_migration "063_backfill_legacy_media_rooms.sql"

echo "Deployment status:"
docker compose --env-file .env -f "$COMPOSE_FILE" ps
echo "Recent logs:"
docker compose --env-file .env -f "$COMPOSE_FILE" logs --tail="$LOG_LINES"
REMOTE_DEPLOY
