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

This builds the tutor image (`Dockerfile.tutor`) and starts four
containers: `surrealdb`, `open_notebook`, `tutor` (none of them publish a
host port under the overlay), and `caddy` (publishes 80/443 and reverse-
proxies `{$TUTOR_DOMAIN}` to `tutor:5056`).

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
  all four containers `Up` (`tutor` reports `healthy` once its healthcheck
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

## 7. Troubleshooting

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
