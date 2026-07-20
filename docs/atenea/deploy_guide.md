# Atenea — Production Deploy Guide (PR-BT4)

VPS-from-zero walkthrough for standing up a betatester-facing Atenea
instance. Follows the Feature BT deployment-posture invariant: **only the
tutor is publicly reachable, and only through Caddy** — OpenNotebook's
API/UI and SurrealDB are never exposed to the internet.

## 1. Prerequisites

- A VPS (any provider) with a public IPv4/IPv6 address you control.
- Docker Engine + the Docker Compose plugin (`docker compose version` should
  print `v2.24.4` or newer — this guide's overlay uses the `!reset` YAML
  tag, which needs that version; see the "Compose-merge mechanism" note in
  `docker-compose.prod.yml`).
- A domain (or subdomain) you control, with a **DNS A record pointing at
  the VPS's IP**. Caddy needs this to provision TLS automatically — give
  DNS a few minutes to propagate before starting the stack.
- Inbound **ports 80 and 443 open** in the VPS firewall (and any cloud
  provider security group). Caddy uses both: 80 for the ACME HTTP-01
  challenge and plain-HTTP→HTTPS redirects, 443 for the site itself. No
  other inbound port needs to be open — 8502/5055/8000 (OpenNotebook UI/
  API, SurrealDB) stay behind the compose network only.
- At least one LLM provider API key (whichever `TUTOR_LLM_PROVIDER` you
  plan to use), and ideally a second, different-family provider key for
  `TUTOR_VERIFIER_PROVIDER` (self-verification is biased — see
  `.env.production.example`).

## 2. Clone and configure

```bash
git clone <this repo's URL> atenea
cd atenea
cp .env.production.example .env
```

Edit `.env` and fill in every value `.env.production.example` left blank:
`OPEN_NOTEBOOK_ENCRYPTION_KEY` (generate with `openssl rand -hex 32`),
`SURREAL_USER`/`SURREAL_PASSWORD` (strong, generated — this is not the
local-dev `root:root` setup), `SURREAL_NAMESPACE`/`SURREAL_DATABASE`,
`TUTOR_DOMAIN` (the domain from step 1), `TUTOR_PUBLIC_URL` (`https://` +
that same domain), `TUTOR_AUTH_ENABLED=true`, `TUTOR_DAILY_TURN_CAP`,
`TUTOR_LLM_PROVIDER`/`TUTOR_LLM_MODEL` + that provider's API key,
`TUTOR_VERIFIER_PROVIDER`/`TUTOR_VERIFIER_MODEL` + its API key,
`TUTOR_VERIFY_TURNS`/`TUTOR_VERIFY_PROFILE`.

## 3. Bring the stack up

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

This builds the tutor image (`Dockerfile.tutor`) and starts five
containers: `surrealdb`, `open_notebook`, `tutor`, `backup` (none of them
publish a host port under the overlay), and `caddy` (publishes 80/443 and
reverse-proxies `{$TUTOR_DOMAIN}` to `tutor:5056`). `backup` (PR-BT4b, see
§7) starts exporting both databases on a schedule immediately.

Before starting for real, you can render the merged compose model locally
and eyeball it (no containers started):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
```

Confirm `surrealdb`, `open_notebook` and `tutor` show no `ports:` entry at
all in the rendered output, and `caddy` is the only service with
`published: "80"` / `published: "443"`.

## 4. Verify

- `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps` —
  all five containers `Up` (`tutor` reports `healthy` once its healthcheck
  passes, ~15–30s after start).
- `curl -I https://<your-domain>/` — expect a `200` (or a redirect chain
  ending in one) once Caddy has finished issuing the certificate (usually
  seconds to a couple of minutes on first boot).
- `curl https://<your-domain>/health` — the same `GET /health` contract
  from PR-A1 (`{"status": "ok", ...}`), now reachable only over HTTPS.
- Confirm the invariant: `curl http://<your-domain>:8502` and
  `curl http://<your-domain>:5055` must both fail to connect (nothing is
  listening on those ports from outside the VPS).

## 5. Mint testers

Run the CLI inside the running `tutor` container (it talks to SurrealDB
directly, same as local dev — see `tutor/access/__main__.py`):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec tutor \
  python -m tutor.access create <user_id> --label "Their name or handle"
```

This prints a magic link built from `TUTOR_PUBLIC_URL`
(`https://<domain>/?t=<token>`) — shown once. Send it to the tester over
whatever channel you already use (email, chat). They open it, the tutor UI
stores the token client-side and sends it as a Bearer header on every
request from then on (PR-BT1).

Other useful commands, same container:

```bash
python -m tutor.access list      # every provisioned token + status
python -m tutor.access revoke <user_id_or_label>
python -m tutor.access usage     # per-user turn counts (daily cap visibility)
python -m tutor.access share <source_id>   # flip a private source public (PR-BT3)
```

## 6. Update path

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Compose rebuilds only the images that changed and restarts affected
containers; SurrealDB's data volume (`./surreal_data`) and Caddy's TLS
state (`caddy_data` volume) persist across this.

## 7. Backups & restore (PR-BT4b)

The `backup` service (`docker-compose.prod.yml`) reuses the same
`surrealdb/surrealdb:v2` image as `surrealdb` itself (it ships the `surreal`
CLI at `/surreal`) and runs `deploy/backup.sh`, mounted read-only into the
container at `/backup.sh`. It exports **both** databases the stack uses —
OpenNotebook's own (`SURREAL_DATABASE`, default `open_notebook`) and the
tutor's (`TUTOR_SURREAL_DATABASE`, default `atenea`; same `SURREAL_NAMESPACE`
as OpenNotebook, different database — PR-C1) — every
`TUTOR_BACKUP_INTERVAL_HOURS` (default 24), then rotates old dumps, keeping
`TUTOR_BACKUP_KEEP` (default 14) most recent **per database**. No new
credentials: it reads the same `SURREAL_USER`/`SURREAL_PASSWORD`/
`SURREAL_NAMESPACE` the rest of the stack already uses (see
`.env.production.example`).

### Where dumps land

Dated files under the host-mounted `./backups/` directory (created
automatically), one file per database per pass:

```
backups/
  open_notebook-20260720-030000.surql
  atenea-20260720-030000.surql
  open_notebook-20260721-030000.surql
  atenea-20260721-030000.surql
  ...
```

The `backup` container publishes no port and is invisible to the internet —
same posture as `surrealdb`/`open_notebook` under this overlay.

### Verify a first dump exists (do this right after standing up the stack)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup /backup.sh
ls -la ./backups
```

This runs one export+rotate pass on demand (the same script the container's
own loop calls, just without `--loop`) and exits — it does not wait for the
next scheduled run. Confirm two new `.surql` files appear (one per
database) and that `docker compose ... logs backup` shows no error. If the
`backup` container itself won't start or keeps restarting, see
Troubleshooting below — `deploy/backup.sh` is plain POSIX `sh`, but the
upstream SurrealDB image is a minimal CLI+server image and its shell
availability was not verified by hand for this PR; the fallback further
down does not depend on it.

### Restore

Restoring imports a `.surql` dump back into a **running** SurrealDB
instance. `surreal import` mirrors `surreal export`'s flags. Run it inside
the `backup` container, which already has both the `surreal` CLI and the
`./backups` directory mounted:

```bash
# OpenNotebook's own database
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup \
  /surreal import --conn http://surrealdb:8000 \
  --user <SURREAL_USER> --pass <SURREAL_PASSWORD> \
  --ns <SURREAL_NAMESPACE> --db open_notebook \
  /backups/open_notebook-<TIMESTAMP>.surql

# The tutor's atenea database
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup \
  /surreal import --conn http://surrealdb:8000 \
  --user <SURREAL_USER> --pass <SURREAL_PASSWORD> \
  --ns <SURREAL_NAMESPACE> --db atenea \
  /backups/atenea-<TIMESTAMP>.surql
```

Substitute the real `SURREAL_USER`/`SURREAL_PASSWORD`/`SURREAL_NAMESPACE`
from your `.env` and the dump filename you want to restore. `surreal
import` writes into the target namespace/database as-is — it does not wipe
it first, so importing into a database that already has rows can produce
duplicates/conflicts. For a real disaster-recovery restore (target
database wiped or gone), this is safe: bring the stack up fresh (new,
empty `./surreal_data`), then run both import commands before pointing
testers at it again.

**Rehearse a restore before inviting testers.** Do this once, on a
throwaway namespace, so a real incident is not the first time you run
these commands:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup \
  /surreal import --conn http://surrealdb:8000 \
  --user <SURREAL_USER> --pass <SURREAL_PASSWORD> \
  --ns restore_drill --db open_notebook_drill \
  /backups/open_notebook-<TIMESTAMP>.surql
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup \
  /surreal sql --conn http://surrealdb:8000 \
  --user <SURREAL_USER> --pass <SURREAL_PASSWORD> \
  --ns restore_drill --db open_notebook_drill \
  --pretty <<< "INFO FOR DB;"
```

Confirm the drill namespace/database actually has your tables and rows,
then move on — no cleanup is required (`restore_drill` never overlaps with
the real `SURREAL_NAMESPACE`), but you may `REMOVE NAMESPACE restore_drill;`
via the same `/surreal sql` invocation if you'd rather not leave it around.

### Fallback if the `backup` container won't start

If `docker compose ... ps` shows `backup` stuck `Restarting` (the container
entrypoint interprets `/backup.sh` via `/bin/sh`, and that assumption turns
out to be wrong for the SurrealDB image tag in use), automatic backups are
down but restores above still work as long as `surrealdb` itself is up
(`/surreal` is invoked by its exact path either way). Drive the same export
from the host instead, e.g. via a host crontab entry that does not need a
shell inside the image at all:

```cron
0 3 * * * cd /path/to/atenea && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T surrealdb /surreal export --conn http://localhost:8000 --user <SURREAL_USER> --pass <SURREAL_PASSWORD> --ns <SURREAL_NAMESPACE> --db open_notebook /mydata/backup-open_notebook-$(date -u +\%Y\%m\%d).surql
```

(`/mydata` is the `surrealdb` service's own existing volume,
`./surreal_data:/mydata` in `docker-compose.yml` — copy the file out with
`docker compose ... cp` afterwards, or add a second bind mount for
`./backups` to that service as a permanent fix.)

## 8. Troubleshooting

- **Certificate never issues / `docker compose logs caddy` shows ACME
  errors.** Almost always DNS: the A record hasn't propagated yet, or
  points at the wrong IP. Verify with `dig +short <your-domain>` from
  outside the VPS and compare against the VPS's public IP. Also confirm
  80/443 are actually reachable from the internet (a cloud firewall/
  security group rule is a common miss even when the OS firewall is
  correct).
- **`docker compose logs caddy`** is the first stop for any TLS/proxy
  issue — Caddy logs ACME challenge attempts, certificate renewal, and
  upstream (tutor) connection errors in one place.
- **502/504 from Caddy.** The `tutor` container isn't up or isn't healthy
  yet — check `docker compose ps` and `docker compose logs tutor`. Caddy
  retries automatically once `tutor` recovers.
- **`docker compose config` still shows old ports after editing the
  overlay.** Confirm your Compose CLI version supports `!reset` (`docker
  compose version`, need v2.24.4+) — on an older CLI, `!reset` is parsed as
  a plain string tag and the merge silently falls back to normal
  append-only `ports` semantics, un-clearing them.
- **A tester hits a 429.** Working as intended — `TUTOR_DAILY_TURN_CAP` was
  reached for that user; `python -m tutor.access usage` shows current
  counts. Raise the cap in `.env` and `up -d` again if needed.
- **A tester gets a friendly "pide tu enlace de acceso" lockout.** Their
  token is missing/invalid/revoked. Check `python -m tutor.access list` and
  re-provision with `create` if needed.
- **`backup` shows `Restarting` in `docker compose ps`.** `docker compose
  logs backup` first. If the log is empty or shows an exec/"not found"
  error for `/bin/sh`, the SurrealDB image tag in use doesn't ship a shell
  — use the host-crontab fallback in §7 ("Fallback if the `backup`
  container won't start") instead; it drives `/surreal` directly and does
  not need one.
