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
