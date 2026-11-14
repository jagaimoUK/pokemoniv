# Compute Engine: nonpublic staging before Railway migration

This is a **staging-only** deployment. No Railway, DNS, authentication, or existing
data should be deleted, overwritten, published, or rotated by following these
steps. Cloud Run PR #88 remains independent of this migration branch.

## Cloud Console VM

Select the new personal Google Cloud project with the available trial credit.
Create VM `pokemoniv-web` in Tokyo (`asia-northeast1-a`), initially `e2-medium`
(4 GiB), Ubuntu 24.04 LTS, 40 GiB standard persistent boot disk, Spot off,
deletion protection on; disable automatic boot disk deletion if available.
Do **not** check public HTTP/HTTPS firewall options or expose port 8787.
Review default SSH firewall exposure; prefer IAP and OS Login. Google Cloud
free-trial credit has an expiry and budget alerts do **not** stop charges.
Verify the price estimate before creating resources.

## Host setup, SSH in browser

```sh
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 git openssl
sudo systemctl enable --now docker
sudo docker compose version

sudo install -d -m 0700 /etc/pokemoniv
sudo install -d -m 0755 /srv/pokemoniv
sudo install -d -m 0711 /srv/pokemoniv/data
sudo install -d -o 10001 -g 10001 -m 0700 /srv/pokemoniv/work

# TEMPORARY staging secret only. Never paste it into a chat or commit it.
{ printf 'PVP_API_KEY='; openssl rand -hex 32; } |
  sudo tee /etc/pokemoniv/pokemoniv.env >/dev/null
sudo chmod 0600 /etc/pokemoniv/pokemoniv.env
```

For production, preserve the old PVP_API_KEY where required by installed clients,
or rotate it deliberately. Check `PVP_MCP_URL` (public HTTPS origin),
`AUTH0_ISSUER`, `AUTH0_ALLOWED_SUB`, `JWT_AUDIENCE`, `PVP_OAUTH_SCOPE`, and
`VISUAL_BACKUP_S3_*` secrets. Do not copy secrets via Git, public HTTP, command
history or chat. An Auth0-enabled deployment requires an HTTPS PVP_MCP_URL.

Checkout the migration branch using read-only authenticated Git access if
this repository is private. **Do not put tokens in the URL or shell command.**
The Compose build context is the repository root (`../..` from the YAML).
Running `docker compose ... config --quiet` is safe before data restoration.

## Restore gate (do not skip)

Earlier checks found ~118 MiB/295 files copied from Railway's
`/data/pvpoke_archives`, but not a fully reconciled point-in-time snapshot.
The source remains the authority for newer writes. Verify archive structure,
SHA256 hashes, SQLite integrity and complete tables, ZIP CRC and data parity.
Transfer source copies privately, restore the contents below
`/srv/pokemoniv/data/pvpoke_archives` *before first app startup* and give that
directory and its files to UID/GID 10001. Reject malformed archives (symlink,
absolute path, parent traversal, collisions) before extraction. Never overwrite
VM-created databases with a stale backup.

The work directory is independently persisted at
`/srv/pokemoniv/work` (maps to `/home/appuser/pvpoke_automation_web`).
Previously checked sources were empty. Also reconcile separate
`iv-visual-backups` object storage and the same-browser migration JSON;
their export completion was not established. Keep originals intact.
For final cutover, freeze source writes and reconcile the latest data,
especially credential revocations and modified presets.

## Private validation

After safe restore and secrets provisioning:

```sh
sudo docker compose -f deploy/compute-engine/compose.yaml config --quiet
sudo docker compose -f deploy/compute-engine/compose.yaml up -d --build
sudo docker compose -f deploy/compute-engine/compose.yaml ps
curl -fsS http://127.0.0.1:8787/health
```

The container only binds to VM loopback. Check named saved parties, auth
and revoked credentials, meta presets, normal/detailed IV calculations,
completed long-running jobs, history after restart, Android integration
and visual learning. A green health endpoint is not proof of migration success.

## Production cutover (separate approval)

A Railway-owned `*.up.railway.app` URL cannot be transferred to Compute Engine.
Plan a new domain/HTTPS reverse proxy (leave backend loopback-bound), IAM and
firewall restrictions, OAuth redirect configuration, backups/snapshots, logs,
retention, cost alerts and rollback before public ingress. Preserve Railway
until final source-to-target reconciliation and explicit approval; rollback
by disabling only the new VM's traffic, without modifying source data.
