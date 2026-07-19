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
