# CORE_CHANGES.md

Registry of every modification to OpenNotebook core code (anything outside `tutor/` and Atenea-specific docs). Required by the **extension-before-modification** rule in AGENTS.md: extensions (new modules, REST API consumers, hooks) don't need an entry here; core edits always do.

Each entry records: files touched, why extension wasn't viable, and upstream-merge risk (what breaks or conflicts when we pull upstream).

Format:

```
## <short title> (<date>, <branch/PR>)
- Files: <paths>
- Reason: <why this had to be a core change>
- Upstream-merge risk: <low/medium/high + what to watch for>
```

---

## Vertex AI credentials not applied from UI config (2026-07, fix/vertex-credentials-env)

- Files: `api/credentials_service.py`, `open_notebook/ai/key_provider.py`, `open_notebook/ai/models.py`
- Reason: Esperanto's Vertex providers only read project/location/credentials from env vars (`VERTEX_PROJECT`, `VERTEX_LOCATION`, `GOOGLE_APPLICATION_CREDENTIALS`), ignoring the config dict. UI-entered Vertex credentials failed with "Google Cloud project ID not found". Fix extracts `apply_vertex_env()` and mirrors credential fields into env vars at model build/test time. Can't be done via extension: the bug is inside core credential/model plumbing.
- Upstream-merge risk: **medium** — touches `key_provider.py` internals that upstream refactors could move. Candidate for an upstream PR (benefits all OpenNotebook users), which would reduce this entry to zero once mer
## Tutor service in docker-compose (2026-07-12, feature/dx/compose / PR-DX1)

- Files: `docker-compose.yml` (new `tutor` service appended; existing services untouched), `Dockerfile.tutor` (new file at repo root)
- Reason: one-command startup requires wiring the tutor into the shared compose file, which is upstream's. `Dockerfile.tutor` is a new file (pure extension) but lives outside `tutor/`, so it is logged here per the review checklist.
- Upstream-merge risk: **low** — the service is appended at the end of `docker-compose.yml`; upstream edits to its own services merge cleanly. `Dockerfile.tutor` cannot conflict (upstream has no such file).

## Eval harness Make target + gitignore (2026-07-12, feature/e2/session-quality / PR-E2)

- Files: `Makefile` (new `eval-tutor` target appended, alongside `tutor`/`check-tutor`), `.gitignore` (ignore `eval_runs/`)
- Reason: the prompt-evaluation harness lives in `tutor/eval/` (pure extension) but its runner entrypoint and output dir must be wired into the repo's `Makefile` and `.gitignore`, which are core. All pedagogy logic, personas, rubric and judge are inside `tutor/`; only these two one-line hooks are outside it.
- Upstream-merge risk: **low** — both are appends at end-of-file; upstream edits elsewhere merge cleanly.

## Source-scoped vector search (2026-07-14, feature/m2/scoped-search / PR-M2)

- Files:
  - `open_notebook/database/migrations/23.surrealql` (+ `23_down.surrealql`) — redefines `fn::vector_search` with a new final `$source_id: option<string>` parameter. `NONE` (default) reproduces migration 9's behavior exactly; when set, the source-side branches are filtered to `<string>source.id = $source_id` and the notes branch is skipped entirely (a note is never part of a source).
  - `open_notebook/domain/notebook.py::vector_search` — new last kwarg `source_id: str | None = None`, always bound as the function's 6th positional arg (`$source_id`) so arity matches the migration 23 definition.
  - `api/models.py::SearchRequest` — new `source_id: Optional[str] = None` field (vector search only; ignored for text search).
  - `api/routers/search.py` — passes `search_request.source_id` into `vector_search(...)` on the vector branch only; text branch untouched.
  - Additive test (CI-only on this repo's local Python 3.10 sandbox, real on GitHub CI's 3.12/uv): `tests/test_search_source_filter.py` — pydantic/signature-level assertions only (`SearchRequest.source_id` defaults to `None`, `inspect.signature(vector_search)` has a `source_id` param defaulting to `None`); no DB access.
- Reason: extension wasn't viable — the filter has to run DB-side, inside `fn::vector_search` itself, so that similarity ranking and `LIMIT $match_count` happen *within* the chosen source rather than over the whole corpus and then be filtered down client-side (which is what PR-M1 did as a stopgap, and what this PR replaces with real scoping). That ranking step cannot be reproduced correctly from outside the function.
- Upstream-merge risk: **medium** — any upstream redefinition of `fn::vector_search` (a new migration touching the same function) will conflict with migration 23's `REMOVE FUNCTION` / `DEFINE FUNCTION` pair, since both edit the same object. The new parameter defaults to `NONE` and the down-migration (`23_down.surrealql`, byte-identical to migration 9's body) fully restores pre-PR-M2 behavior, so the redefinition is cleanly revertible even if upstream moves the function elsewhere.
- Revert recipe: run `23_down.surrealql` (drops the DB function back to migration 9's exact body), then drop the `source_id` parameter at the three Python call sites (`domain/notebook.py::vector_search`, `api/models.py::SearchRequest`, `api/routers/search.py`'s vector branch). The tutor side (`tutor/clients/open_notebook.py::search`, `tutor/tools/content.py`, `tutor/session/grounding.py`) needs no change on revert: `source_id` is only ever included in the outgoing request body when set, so an older core that ignores the extra field falls back automatically to the tutor-side `parent_id` filter that PR-M1 already put in place as defense-in-depth.

## .github/workflows/ci-failure-logs.yml (new, 2026-07-19)
- **Why:** the agents' sandbox cannot reach api.github.com, so CI failures were
  unreadable without the developer manually pasting logs. On any failed Tests /
  Tutor CI run this workflow pushes the failed jobs' log tails to the `ci-logs`
  branch, readable via `git fetch origin ci-logs`.
- **Upstream-merge risk:** none — new file, no upstream counterpart.

## .github/workflows/tutor-eval.yml (new, 2026-07-19 — PR-DX3)
- **Why:** runs the PR-E2 pedagogy eval harness in CI (dispatch or on prompt/eval
  changes), publishing scored runs to the accumulating `eval-reports` branch so
  agents iterate the pedagogy prompts against measurements without the
  developer's machine. Needs repo secret DEEPSEEK_API_KEY (or another provider).
- **Upstream-merge risk:** none — new file, no upstream counterpart.

### Update (2026-07-19 — PR-W1-eval addendum, `feature/w/verify-turn`)
- **Files:** `.github/workflows/tutor-eval.yml` only (edited, not new).
- **Why:** the DX3 merge gate was vacuous for PR-W1 — the 4 scripted personas
  ran ungrounded with verification off, so the workflow never exercised the
  closed-world prompt or the verification gate it was meant to check. Added
  four `workflow_dispatch` inputs (`verify_turns` default `grounded`,
  `verify_profile` default `high`, `verifier_provider`/`verifier_model`
  passthrough, empty default = unset) mapped to `TUTOR_VERIFY_TURNS` /
  `TUTOR_VERIFY_PROFILE` / `TUTOR_VERIFIER_PROVIDER` / `TUTOR_VERIFIER_MODEL`
  env vars in the "Run eval" step. All tutor-side logic (the new grounded
  persona, the grounding/verification wiring in `tutor/eval/runner.py`) lives
  under `tutor/`; this is only the CI passthrough.
- **Upstream-merge risk:** none — same as above, no upstream counterpart.

## Production deploy bundle: compose overlay + Caddy reverse proxy (2026-07-20, feature/bt4/deploy / PR-BT4)

- Files: `docker-compose.prod.yml` (new file, repo root), `Caddyfile` (new
  file, repo root). `.env.production.example` and `docs/atenea/deploy_guide.md`
  are also new but are Atenea-specific docs/env-template files (same status
  as `.env.example`), not logged here.
- Reason: one-command production startup requires an overlay wired against
  the shared `docker-compose.yml` (upstream's file) and a proxy config file
  that mounts into it — both are pure additions (no existing service
  definition in `docker-compose.yml` is touched) but live outside `tutor/`,
  so the review checklist requires logging them here, same precedent as
  `Dockerfile.tutor` (PR-DX1).
- Compose-merge mechanism used to clear published ports: `ports` is a
  compose-spec "unique resource" sequence (merge key `{ip, target,
  published, protocol}`) — override entries are *appended*, not used to
  replace the base list, so a bare `ports: []` in the overlay would be a
  no-op and silently leave `surrealdb`/`open_notebook`/`tutor`'s host ports
  published. The overlay instead uses the custom `!reset` YAML tag
  (compose-spec "Reset value", Compose CLI v2.24.4+), which clears an
  inherited attribute to its type default regardless of merge rules:
  `ports: !reset []` on all three internal services. Verified locally: a
  plain `yaml.safe_load` on the overlay raises `ConstructorError` on the
  `!reset` tag (asserted in `tests_tutor/test_compose_prod.py`), confirming
  the tag is present and not silently ignored/downgraded to a normal list.
- Upstream-merge risk: **low** — `docker-compose.prod.yml` and `Caddyfile`
  are both new files with no upstream counterpart; `docker-compose.yml`
  itself is untouched by this PR (the overlay only references its service
  names, it does not edit them).
## Beta data backups: `backup` service + script (2026-07-20, feature/bt4b/backups / PR-BT4b)

- Files: `docker-compose.prod.yml` (edited — new `backup` service appended
  to the PR-BT4 overlay), `deploy/backup.sh` (new file, repo root's new
  `deploy/` directory). `.env.production.example` and
  `docs/atenea/deploy_guide.md` are also touched but are Atenea-specific
  docs/env-template files (same status as `.env.example`), not logged here.
- Reason: same rationale as PR-BT4's entry above — the backup service has
  to be wired into the shared production overlay (`docker-compose.prod.yml`,
  itself outside `tutor/`) to run alongside `surrealdb`/`open_notebook`/
  `tutor`/`caddy`, and `deploy/backup.sh` is a new file living outside
  `tutor/` (a pure addition, no existing file touched), so both are logged
  here per the review checklist, same precedent as `Dockerfile.tutor`
  (PR-DX1) and `Caddyfile`/`docker-compose.prod.yml` itself (PR-BT4).
- Design note (smallest-reading decision, flagged for the developer): the
  `backup` service reuses the base `surrealdb` service's own image tag
  (`surrealdb/surrealdb:v2`) and overrides its entrypoint to
  `/bin/sh /backup.sh --loop`, per the contract's literal text ("uses the
  same SurrealDB image ... simple shell loop", "`docker compose ... exec
  backup sh /backup.sh`"). Web research during implementation turned up
  credible (but not locally verifiable — no Docker daemon in this sandbox)
  evidence that the official `surrealdb/surrealdb` image may be a minimal
  CLI+server image without a shell (a GitHub issue requesting bash be added
  to it, workaround = copying busybox in). Rather than unilaterally
  introducing a new multi-stage `Dockerfile.backup` (outside this PR's
  scope guard), the implementation follows the signed contract as written
  and documents both a first-deploy verification step and a host-crontab
  fallback that does not depend on a shell existing inside the image
  (`docs/atenea/deploy_guide.md` §7) — the failure mode if the assumption
  is wrong is loud (`backup` container stuck `Restarting`), not silent.
- Upstream-merge risk: **low** — `docker-compose.prod.yml`'s edit is a pure
  append (new service block, existing services untouched) and
  `deploy/backup.sh` is a new file with no upstream counterpart.
