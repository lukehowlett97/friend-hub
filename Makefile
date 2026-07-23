# Top-level Makefile for friend_hub

#–– Default goal ––#
.DEFAULT_GOAL := help

-include .env.deploy
-include .env
-include backend/.env

#–– Configurable variables ––#
NPM         ?= npm
DC          ?= docker-compose
TF          ?= terraform
TF_DIR      ?= infra/terraform
TF_ARGS     ?=
MESSENGER_DATA_ROOT ?= importers/facebook_messenger/data
FB_DATA_MAY_2026_SOURCE ?= /path/to/messenger-export
MESSENGER_EXPORT_ROOT ?= $(MESSENGER_DATA_ROOT)
MESSENGER_CHAT_FOLDER ?= example-group
MESSENGER_ROOM_ID ?= main
MESSENGER_SENDER_MAP ?= /path/to/sender-map.txt
MESSENGER_IMPORT_ARGS ?=

FETCH_SOURCE ?= $(FB_DATA_MAY_2026_SOURCE)
FETCH_LABEL  ?= example-group
FETCH_OUTPUT ?= $(MESSENGER_DATA_ROOT)/example-group
FETCH_ARGS ?=

HOST        ?= 127.0.0.1
PORT        ?= 8000

DB_USER     ?= chatuser
DB_PASS     ?= changeme
DB_NAME     ?= chatapp
DB_PORT     ?= 5432
DB_URL      = postgresql://$(DB_USER):$(DB_PASS)@$(HOST):$(DB_PORT)/$(DB_NAME)

# Remote deployment
TF_SSH_SERVER = $(shell { $(TF) -chdir=$(TF_DIR) output -raw ssh_command 2>/dev/null || sed -n '/"ssh_command"/,/}/s/.*"value": "\(ssh [^"]*\)".*/\1/p' $(TF_DIR)/terraform.tfstate 2>/dev/null; } | sed 's/^ssh //')
SERVER       ?= $(TF_SSH_SERVER)
APP_DIR      ?= /opt/friend-hub/app
DEPLOY_REF   ?= HEAD
COMPOSE_FILE ?= deploy/docker-compose.prod.yml
ENV_FILE     ?= .env.prod
SSH_OPTS     ?= -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new
ALLOW_DIRTY  ?= 0
LOG_LINES    ?= 120

# Backend virtualenv — lives inside backend/ so it's close to the source
VENV        = backend/.venv
PYTHON      = $(CURDIR)/$(VENV)/bin/python3
PIP         = $(CURDIR)/$(VENV)/bin/pip

#–– Phony targets ––#
.PHONY: help deps up down backend frontend migrate migrate-file seed test clean inspect truncate-db gen-invite enrol-users import-messenger import-messenger-dry-run list-messenger-labels fetch-messenger fetch-messenger-dry-run terraform-init terraform-plan terraform-apply terraform-destroy plan apply destroy deploy deploy-status deploy-logs deploy-restart connect

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  deps        Create venv and install all dependencies"
	@echo "  up          Start Docker services (Postgres)"
	@echo "  down        Stop Docker services"
	@echo "  backend     Run FastAPI dev server  (needs: make deps && make up)"
	@echo "  frontend    Run Vite dev server"
	@echo "  migrate     Apply database schema (init.sql)"
	@echo "  seed        Seed database with sample data"
	@echo "  test        Run backend tests"
	@echo "  clean       Remove caches and build artefacts"
	@echo "  inspect     List users in the database"
	@echo "  gen-invite  Generate an admin invite code: make gen-invite USER=techlett"
	@echo "  manage-room Manage rooms: make manage-room CMD='create-room --slug gc-plus --name GC+'"
	@echo "  enrol-users Enrol all active users into the main room"
	@echo "  migrate-file Run a specific migration: make migrate-file FILE=037_add_notification_preferences.sql"
	@echo "  truncate-db Wipe users and messages (keeps schema)"
	@echo "  import-messenger-dry-run Preview configured Messenger import"
	@echo "  import-messenger Import configured Messenger chat into DB"
	@echo "  list-messenger-labels List inbox labels in configured FB export zips"
	@echo "  fetch-messenger-dry-run Preview Messenger zip extraction"
	@echo "  fetch-messenger Extract labelled chat from FB export zips"
	@echo "  plan        Run Terraform plan"
	@echo "  apply       Run Terraform apply"
	@echo "  destroy     Run Terraform destroy"
	@echo "  deploy      Upload local Git archive and restart the app on the VPS"
	@echo "  deploy-status Show remote Docker Compose status"
	@echo "  deploy-logs Tail remote Docker Compose logs"
	@echo "  deploy-restart Restart remote Docker Compose services"
	@echo "  connect     SSH into the VPS"
	@echo ""
	@echo "Deployment defaults to Terraform output ssh_command; override with SERVER=deploy@host."

# ── Dependencies ────────────────────────────────────────────────────────────

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet

deps: $(VENV)
	$(PIP) install \
		"fastapi>=0.104" "uvicorn[standard]>=0.24" "websockets>=12" \
		"asyncpg>=0.29" "sqlalchemy[asyncio]>=2.0" \
		"python-dotenv>=1.0" "pydantic-settings>=2.0" \
		"pillow>=11.0" "httpx>=0.27" "pytest>=9" "pytest-asyncio>=0.23"
	cd frontend && $(NPM) install
	@echo ""
	@echo "✓ Dependencies installed. Run 'make backend' and 'make frontend'."

# ── Docker ──────────────────────────────────────────────────────────────────

up:
	$(DC) up -d

down:
	$(DC) down

# ── Run ─────────────────────────────────────────────────────────────────────

backend: $(VENV)
	cd backend && $(PYTHON) -m uvicorn app.main:app \
		--host $(HOST) \
		--port $(PORT) \
		--reload

frontend:
	cd frontend && npx vite

# ── Database ─────────────────────────────────────────────────────────────────

migrate:
	psql "$(DB_URL)" -f backend/migrations/init.sql

seed:
	psql "$(DB_URL)" -f backend/migrations/seed.sql

inspect:
	psql "$(DB_URL)" -c "SELECT session_id, nickname, last_seen FROM users;"

gen-invite: $(VENV)
	@test -n "$(USER)" || (echo "Usage: make gen-invite USER=<username>"; exit 1)
	cd backend && $(PYTHON) scripts/gen_invite.py $(USER)

manage-room: $(VENV)
	@test -n "$(CMD)" || (echo "Usage: make manage-room CMD='<subcommand> [args]'"; echo "  CMD='list-rooms'"; echo "  CMD='create-room --slug gc-plus --name GC+'"; echo "  CMD='create-admin --username alice --room-slug gc-plus'"; echo "  CMD='add-member --username bob --room-slug gc-plus'"; echo "  CMD='list-members --room-slug gc-plus'"; echo "  CMD='gen-invite --room-slug gc-plus'"; exit 1)
	cd backend && $(PYTHON) scripts/manage_room.py $(CMD)

migrate-file: $(VENV)
	@test -n "$(FILE)" || (echo "Usage: make migrate-file FILE=<filename.sql>"; exit 1)
	cd backend && $(PYTHON) scripts/run_migrations.py $(FILE)

enrol-users: $(VENV)
	cd backend && $(PYTHON) scripts/enrol_users.py

truncate-db:
	psql "$(DB_URL)" -c "TRUNCATE TABLE users, messages RESTART IDENTITY CASCADE;"
	@echo "Tables truncated."

import-messenger-dry-run: $(VENV)
	cd backend && DEBUG="$(DEBUG)" DATABASE_HOST="$(DATABASE_HOST)" DATABASE_PORT="$(DATABASE_PORT)" DATABASE_USER="$(DATABASE_USER)" DATABASE_PASSWORD="$(DATABASE_PASSWORD)" DATABASE_NAME="$(DATABASE_NAME)" $(PYTHON) -m app.importers.facebook_messenger.cli \
		--export-root "$(MESSENGER_EXPORT_ROOT)" \
		--chat-folder "$(MESSENGER_CHAT_FOLDER)" \
		--room-id "$(MESSENGER_ROOM_ID)" \
		--sender-map "$(MESSENGER_SENDER_MAP)" \
		--dry-run \
		$(MESSENGER_IMPORT_ARGS)

import-messenger: $(VENV)
	cd backend && DEBUG="$(DEBUG)" DATABASE_HOST="$(DATABASE_HOST)" DATABASE_PORT="$(DATABASE_PORT)" DATABASE_USER="$(DATABASE_USER)" DATABASE_PASSWORD="$(DATABASE_PASSWORD)" DATABASE_NAME="$(DATABASE_NAME)" $(PYTHON) -m app.importers.facebook_messenger.cli \
		--export-root "$(MESSENGER_EXPORT_ROOT)" \
		--chat-folder "$(MESSENGER_CHAT_FOLDER)" \
		--room-id "$(MESSENGER_ROOM_ID)" \
		--sender-map "$(MESSENGER_SENDER_MAP)" \
		$(MESSENGER_IMPORT_ARGS)

list-messenger-labels:
	@test -n "$(FETCH_SOURCE)" || (echo "Usage: make list-messenger-labels FETCH_SOURCE=..."; exit 1)
	python3 importers/facebook_messenger/messenger_zip_fetcher/fetch.py \
		--source "$(FETCH_SOURCE)" \
		--list-labels

fetch-messenger-dry-run:
	@test -n "$(FETCH_SOURCE)" || (echo "Usage: make fetch-messenger FETCH_SOURCE=... FETCH_LABEL=... FETCH_OUTPUT=..."; exit 1)
	python3 importers/facebook_messenger/messenger_zip_fetcher/fetch.py \
		--source "$(FETCH_SOURCE)" \
		--label "$(FETCH_LABEL)" \
		--output "$(FETCH_OUTPUT)" \
		--dry-run \
		$(FETCH_ARGS)

fetch-messenger:
	@test -n "$(FETCH_SOURCE)" || (echo "Usage: make fetch-messenger FETCH_SOURCE=... FETCH_LABEL=... FETCH_OUTPUT=..."; exit 1)
	python3 importers/facebook_messenger/messenger_zip_fetcher/fetch.py \
		--source "$(FETCH_SOURCE)" \
		--label "$(FETCH_LABEL)" \
		--output "$(FETCH_OUTPUT)" \
		$(FETCH_ARGS)

# ── Terraform ────────────────────────────────────────────────────────────────

terraform-init:
	$(TF) -chdir=$(TF_DIR) init

terraform-plan: terraform-init
	$(TF) -chdir=$(TF_DIR) plan $(TF_ARGS)

terraform-apply: terraform-init
	$(TF) -chdir=$(TF_DIR) apply $(TF_ARGS)

terraform-destroy: terraform-init
	$(TF) -chdir=$(TF_DIR) destroy $(TF_ARGS)

plan: terraform-plan

apply: terraform-apply

destroy: terraform-destroy

# ── Deployment ───────────────────────────────────────────────────────────────

deploy:
	@test -n "$(SERVER)" || (echo "Usage: make deploy SERVER=deploy@your-server-ip"; exit 1)
	SERVER="$(SERVER)" APP_DIR="$(APP_DIR)" DEPLOY_REF="$(DEPLOY_REF)" COMPOSE_FILE="$(COMPOSE_FILE)" ENV_FILE="$(ENV_FILE)" SSH_OPTS="$(SSH_OPTS)" ALLOW_DIRTY="$(ALLOW_DIRTY)" LOG_LINES="$(LOG_LINES)" ./deploy/deploy.sh

deploy-status:
	@test -n "$(SERVER)" || (echo "Usage: make deploy-status SERVER=deploy@your-server-ip"; exit 1)
	ssh $(SSH_OPTS) $(SERVER) '\
		cd $(APP_DIR); \
		docker compose --env-file .env -f $(COMPOSE_FILE) ps \
	'

deploy-logs:
	@test -n "$(SERVER)" || (echo "Usage: make deploy-logs SERVER=deploy@your-server-ip"; exit 1)
	ssh $(SSH_OPTS) $(SERVER) '\
		cd $(APP_DIR); \
		docker compose --env-file .env -f $(COMPOSE_FILE) logs -f --tail=$(LOG_LINES) \
	'

deploy-restart:
	@test -n "$(SERVER)" || (echo "Usage: make deploy-restart SERVER=deploy@your-server-ip"; exit 1)
	ssh $(SSH_OPTS) $(SERVER) '\
		cd $(APP_DIR); \
		docker compose --env-file .env -f $(COMPOSE_FILE) restart \
	'

connect:
	ssh $(SSH_OPTS) $(SERVER)

# ── Tests ────────────────────────────────────────────────────────────────────

test: $(VENV)
	cd backend && for test_file in tests/test_*.py; do \
		$(PYTHON) -m pytest -q "$$test_file" || exit 1; \
	done

# ── Clean ────────────────────────────────────────────────────────────────────

clean:
	rm -rf $(VENV) backend/.pytest_cache frontend/node_modules frontend/dist
	find backend -type d -name __pycache__ -exec rm -rf {} +
