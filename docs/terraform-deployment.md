# Terraform Deployment

This deploys Friend Hub to one Hetzner Cloud VPS with Docker Compose, Caddy, the FastAPI backend, the Vite frontend, and a local PostgreSQL container.

Terraform owns infrastructure only. App code, runtime secrets, Docker Compose startup, and restarts are handled by `make deploy`.

## Files

- `infra/terraform/` contains the Hetzner server, firewall, SSH key, variables, outputs, and cloud-init template.
- `deploy/docker-compose.prod.yml` defines Caddy, frontend, backend, and Postgres.
- `deploy/deploy.sh` uploads a local Git archive and `.env.prod` over SSH.
- `deploy/prod.env.example` is the production env template. Copy it to `.env.prod`.
- `deploy/backup-postgres.sh` creates local compressed Postgres dumps.

## Secrets

Terraform must not receive app runtime secrets. Keep app secrets in local, ignored files and upload them during deploy.

Do not commit:

- `infra/terraform/terraform.tfvars`
- `*.tfstate`
- `.terraform/`
- `.env.prod`
- `deploy/prod.env`
- database backups

The default deploy path streams `git archive HEAD` over SSH. The VPS does not need a GitHub deploy key, GitHub private key, or SSH agent forwarding.

SSH agent forwarding or a GitHub deploy key can work, but they are not the default. Agent forwarding exposes your local agent socket to the remote host during the SSH session, and deploy keys add another secret to manage on the VPS.

## First Deploy

Create a Hetzner Cloud API token and make sure your SSH public key exists locally.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with infrastructure values only:

```hcl
hcloud_token        = "..."
project_name        = "friend-hub"
environment         = "prod"
server_type         = "cax11"
location            = "nbg1"
domain_name         = "chat.example.com"
ssh_public_key_path = "~/.ssh/id_ed25519.pub"
allowed_ssh_ips     = ["203.0.113.10/32"]
```

Provision the server:

```bash
make plan
make apply
```

If DNS is manual, point the domain `A` record to the `server_ipv4` output. Caddy cannot issue HTTPS certificates until DNS reaches the VPS.

Create the local production env file:

```bash
cp deploy/prod.env.example .env.prod
```

Edit `.env.prod` with real values. At minimum, set a real `DOMAIN_NAME`, database password, app secret, invite code, and matching CORS origin.

Deploy the app:

```bash
make deploy
```

`make deploy` defaults to the Terraform `ssh_command` output. Override it when needed:

```bash
make deploy SERVER=deploy@203.0.113.10
```

The deploy command refuses dirty working trees because `git archive HEAD` only includes committed tracked files. To deploy the current `HEAD` anyway:

```bash
make deploy ALLOW_DIRTY=1
```

## Server Checks

```bash
make deploy-status
make deploy-logs
```

Useful health checks:

```bash
curl https://<domain>/api/v1/health
ssh deploy@<server-ip> 'cd /opt/friend-hub/app && docker compose --env-file .env -f deploy/docker-compose.prod.yml exec postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

The frontend should load at `https://<domain>`. The WebSocket route is `/ws/{session_id}` and should connect as `wss://<domain>/ws/<session_id>`.

## Backups

Cloud-init enables `friend-hub-backup.timer`, which runs nightly at 03:15 server time.

Backups are written to:

```text
/opt/friend-hub/backups
```

Before the first successful deploy, the backup script exits cleanly with `No app env found; skipping backup`.

Run one manually:

```bash
ssh deploy@<server-ip> 'systemctl start friend-hub-backup.service && ls -lh /opt/friend-hub/backups'
```

Restore a dump:

```bash
ssh deploy@<server-ip>
cd /opt/friend-hub/app
gunzip -c /opt/friend-hub/backups/friend-hub-YYYY-MM-DD.sql.gz \
  | docker compose --env-file .env -f deploy/docker-compose.prod.yml exec -T postgres psql -U chatuser chatapp
```

Postgres data lives in the server-local Docker named volume `postgres_data`. Local VPS backups are not disaster-proof. Copy dumps to storage outside the server before destructive infrastructure work.

## Terraform Lifecycle

`terraform apply` provisions and updates infrastructure. It does not deploy code, upload `.env`, or restart the app.

These survive normal `terraform apply` runs:

- the VPS
- Docker volumes
- uploaded app files
- `/opt/friend-hub/app/.env`
- `/opt/friend-hub/backups`

`terraform destroy` deletes the VPS. That also deletes Docker volumes, uploaded app files, the uploaded `.env`, and local backups on that server unless copied elsewhere first.

If Hetzner returns `resource_unavailable` during server placement, the chosen `server_type` is temporarily unavailable in the configured `location`. Change `location` in `infra/terraform/terraform.tfvars` to another Hetzner region, such as `fsn1` or `nbg1`, then run `make apply` again. You can also test a one-off location without editing the file:

```bash
make plan TF_ARGS='-var location=fsn1'
make apply TF_ARGS='-var location=fsn1'
```

Terraform keeps any resources that were created before the failure in state, so a retry should reuse them rather than recreate them.

## Acceptance Checklist

- Terraform creates the Hetzner server, SSH key, firewall, deploy user, Docker, and base directories.
- Terraform state does not contain app runtime secrets.
- SSH only accepts connections from `allowed_ssh_ips`.
- Only ports `80` and `443` are public for the app.
- `make deploy` uploads committed code and `.env.prod` over SSH.
- `https://<domain>` serves the frontend with valid HTTPS.
- `https://<domain>/api/v1/health` returns healthy JSON.
- WebSocket traffic works through `/ws/<session_id>`.
- Backend reaches Postgres at `postgres:5432`.
- Postgres data survives container restart/rebuild through the `postgres_data` named volume.
- Nightly compressed DB backups are created and old backups are pruned.
