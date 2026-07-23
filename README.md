# Friend Hub

Friend Hub is a self-hosted group chat and shared social hub for a small,
trusted community. It combines real-time chat, rooms, events, photos,
polls, reminders, notes, search, notifications, and optional AI-assisted
features in one web application.

> This project is under active development. It is suitable for personal or
> small-group deployments; review the security and deployment documentation
> before exposing an instance to the public internet.

## Stack

- React and Vite frontend
- FastAPI and WebSockets backend
- PostgreSQL database
- Docker Compose for local services
- Terraform and Caddy deployment examples for a small VPS

## Quick start

### Prerequisites

- Python 3.12+
- Node.js 18+
- Docker and Docker Compose
- Poetry, or a Python virtual environment with the backend dependencies

### Configure

Copy the example environment files and replace the development values:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Never commit either `.env` file. Keep production secrets outside the
repository.

### Run locally

```bash
make up
make migrate-file FILE=061_add_public_demo_room.sql
make backend
make frontend
```

The API runs on `http://localhost:8000` and the Vite development server runs
on `http://localhost:5173`.

Open `http://localhost:5173/demo` to try the public demo room. It creates a
temporary display name and does not create an account.

Useful commands:

```bash
make test
cd frontend && npm run build
```

## Import an existing Facebook Messenger chat

Friend Hub includes a developer importer for bringing historical Facebook
Messenger group chats into the normal Friend Hub chat history. It can import
messages, participants, timestamps, reactions, links, and supported media from
an extracted Facebook data export.

1. Request and download your Facebook data export with Messenger messages
   included.
2. Extract the export somewhere outside this repository.
3. Set `MESSENGER_EXPORT_ROOT`, `MESSENGER_CHAT_FOLDER`,
   `MESSENGER_ROOM_ID`, and `MESSENGER_SENDER_MAP` in your local environment.
4. Preview the import:

   ```bash
   make import-messenger-dry-run
   ```

5. Run the import when the preview is correct:

   ```bash
   make import-messenger
   ```

The detailed importer notes are in
[`docs/phase_messenger_importer.md`](docs/phase_messenger_importer.md).
Messenger exports contain private conversations and media, so keep the export
outside the repository, do not commit it, and run imports only on a trusted
deployment.

## Deployment

Deployment notes and a Terraform example for Hetzner Cloud are in
[`docs/terraform-deployment.md`](docs/terraform-deployment.md). The
production compose file and Caddy configuration are in [`deploy/`](deploy/).

Read [`docs/phase_security_requirements.md`](docs/phase_security_requirements.md)
and [`docs/DEPLOYMENT_NOTES.md`](docs/DEPLOYMENT_NOTES.md) before deploying.

## Project documentation

The [`docs/`](docs/) directory contains setup notes, operational guidance,
feature plans, and the current roadmap. The project is intentionally
incremental; some documents describe planned or experimental functionality.

## Privacy and data

Runtime uploads, databases, logs, backups, and environment files are local
deployment data and are intentionally excluded from version control. Do not
place private conversations, production exports, or user-uploaded media in
the repository.

## License

This project is released under the MIT License; see [`LICENSE`](LICENSE).
