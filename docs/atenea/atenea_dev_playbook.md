# Atenea — Development Playbook (v1)

> Operational plan for agents continuing development. Read *after* `atenea_context.md`, `atenea_pr_plan.md`, and `AGENTS.md`. This document contains: the current state, the next PR contracts, and the recurring checklists (review, CI, upstream sync). Architects update it when contracts change; implementers never edit contracts here.

## 0. Current State (2026-07-12)

- Fork of OpenNotebook at `open-notebook/`, on `main`, up to date with origin. No Atenea code exists yet.
- Repo hygiene done: `core.autocrlf=input` set locally; working tree clean except the **uncommitted Vertex credentials fix** (see PR-0 below).
- `CORE_CHANGES.md` created at the repo root, with the Vertex fix as its first entry.
- Decisions fixed: tutor service lives in **`tutor/`**; Python **3.12** via `uv`; repo name stays `open-notebook` for now (rename = open decision).
- No `upstream` remote configured yet (see §4).

## 1. Immediate Queue (ordered)

### PR-0 — Commit the pending Vertex fix *(before anything else)*

The working tree contains a real, tested fix (`api/credentials_service.py`, `open_notebook/ai/key_provider.py`, `open_notebook/ai/models.py`) that makes UI-entered Vertex AI credentials work. It must not stay uncommitted.

- Branch: `fix/vertex-credentials-env`
- Commit: `fix: mirror Vertex credentials into env vars so UI-entered credentials apply`
- Include the `CORE_CHANGES.md` entry in the same PR.
- Optional follow-up (developer's call): open the same fix as a PR to upstream OpenNotebook; if merged there, the core divergence disappears.
- Dogfood: enter a Vertex credential in the UI, test it, run a chat completion against a Vertex model.

### PR-A1 — Tutoring service skeleton *(Feature A; the contract below is fixed)*

**Scope.** Bring up the stack via `docker compose up`; create the tutoring service skeleton with a healthcheck that proves connectivity to OpenNotebook's REST API.

**Layout (create exactly this):**

```
tutor/
  __init__.py
  __main__.py          # uvicorn entrypoint: `uv run python -m tutor`
  app.py               # FastAPI app factory
  config.py            # pydantic model + from_env(); all config from env (no new deps)
  clients/
    __init__.py
    open_notebook.py   # thin async client over OpenNotebook's REST API
tests_tutor/           # kept separate from upstream tests/ to avoid merge friction
  test_config.py
  test_health.py       # ON client mocked
docs/atenea/           # copy AGENTS.md + this playbook into the repo here, so the
                       # contract lives in-repo per AGENTS.md §"contract in the repo"
```

**Contract.**

- `GET /health` → `200 {"status": "ok", "open_notebook": {"reachable": true, "indexed_sources": <int>}}`. If OpenNotebook is unreachable: `200 {"status": "degraded", "open_notebook": {"reachable": false, "error": "<msg>"}}` (the service itself being up is still a valid state).
- Env vars (add to `.env.example`, names only): `TUTOR_HOST` (default `0.0.0.0`), `TUTOR_PORT` (default `5056`), `OPEN_NOTEBOOK_API_URL` (default `http://localhost:5055`), plus whatever auth variable OpenNotebook's API requires — **read `api/auth.py` and the routers in `api/routers/` to determine the real endpoint paths and auth mechanism; do not guess.**
- No LLM calls, no DB writes, no profile logic in this PR. Skeleton + connectivity only.
- Makefile: add `tutor` (run service) and `check-tutor` (ruff format --check + ruff check + mypy + pytest over `tutor/` and `tests_tutor/`) targets. `make check-tutor` green = binary "done" criterion.

**Usable when:** with the stack up and ≥1 document indexed in OpenNotebook, `curl localhost:5056/health` returns `status: ok` with `indexed_sources ≥ 1`.

### Then: PR-B1 → PR-C1 → PR-D1 → PR-E1 (V1), per `atenea_pr_plan.md`

Contracts for B1 onward are **not yet written**. Architect step required before each: write the contract into §1 of this playbook (interface signatures, env vars, schemas), get developer sign-off, then hand to an implementer. Serial until Feature D is merged.

## 2. CI Policy

- Upstream `test.yml` covers OpenNotebook. PR-A1 must extend CI so every PR also runs `make check-tutor` (same workflow file, extra job — document it in `CORE_CHANGES.md` only if upstream's workflow file is modified rather than a new workflow added; prefer a new `tutor-ci.yml`).
- Nothing merges red. If a check is flaky, fixing it *is* the next task, not skipping it.
- Recommended (developer, one-time, in GitHub settings): protect `main` — require PRs and green checks.

## 3. Developer Review Checklist (per PR)

1. Does the "How to dogfood this" section work exactly as written? (If you can't use it, the slice is cut wrong — reject.)
2. `make check-tutor` (and upstream tests if core was touched) green locally.
3. Any file changed outside `tutor/`, `tests_tutor/`, `docs/atenea/`? → must have a `CORE_CHANGES.md` entry in the same PR.
4. New config? → must be env-based and reflected in `.env.example` (names only).
5. Any schema? → has `user_id`.
6. Diff readable? Hundreds of whitespace-only changes = line-ending regression; reject and fix git config.
7. Contract drift: does the code match the contract in this playbook? Implementers may not renegotiate contracts inside a PR.

## 4. Upstream Sync Policy

- One-time: `git remote add upstream https://github.com/lfnovo/open-notebook` (verify URL — it's the fork's parent on GitHub).
- Cadence: **before starting each new feature** (not mid-feature), merge `upstream/main` into `main` via a dedicated `chore/upstream-sync` PR. Conflicts concentrated in files listed in `CORE_CHANGES.md` are expected; that file is the conflict map.
- If upstream absorbs one of our fixes (e.g. PR-0), delete its `CORE_CHANGES.md` entry on the next sync.

## 5. Standing Rules Recap (details in AGENTS.md)

Extension before modification (log exceptions in `CORE_CHANGES.md`) · API-first · `user_id` everywhere · config via env only · tools only via the registry (from Feature D) · one PR = one dogfoodable slice · tests mandatory · LF line endings · English in repo · open product decisions b