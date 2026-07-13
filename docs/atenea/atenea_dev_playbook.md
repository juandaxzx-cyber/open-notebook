# Atenea — Development Playbook (v1)

> Operational plan for agents continuing development. Read *after* `atenea_context.md`, `atenea_pr_plan.md`, and `AGENTS.md`. This document contains: the current state, the next PR contracts, and the recurring checklists (review, CI, upstream sync). Architects update it when contracts change; implementers never edit contracts here.

## 0. Current State (updated 2026-07-12, end of day)

- Fork of OpenNotebook at `open-notebook/`. **Five branches delivered and pushed, stacked in this order** (each depends on the previous; dogfood + merge in order):
  1. `fix/vertex-credentials-env` (PR-0) — Vertex credentials fix + `CORE_CHANGES.md`
  2. `feature/a/skeleton` (PR-A1) — `tutor/` FastAPI service, `GET /health`, port 5056, CI (`tutor-ci.yml`), `make check-tutor`, `docs/atenea/`
  3. `feature/b/llm-layer` (PR-B1) — LLM interface wrapping Esperanto, `python -m tutor.llm` CLI
  4. `feature/c/profile` (PR-C1) — learner profile in separate `atenea` SurrealDB database, `GET/PUT /profile`, questionnaire wizard `python -m tutor.profile`
  5. `feature/d/tool-registry` (PR-D1) — ToolSpec/ToolRegistry, entries `content.search`, `profile.read`, `profile.write`, CLI `python -m tutor.tools`
- **Nothing merged to `main` yet** — pending developer dogfood + review. Contracts for each delivered PR are preserved in §1 below as review reference.
- Decisions fixed: tutor service in **`tutor/`**; Python **3.12** via `uv`; tutor data in separate **`atenea`** database (shared SurrealDB instance); current user `TUTOR_USER_ID` (default `juanda`); LLM access only via the tutor's interface wrapping **Esperanto**; repo name stays `open-notebook` for now (rename = open decision).
- Repo hygiene: `core.autocrlf=input`, LF everywhere; `CORE_CHANGES.md` tracks core divergence (2 entries).
- No `upstream` remote configured yet (see §4).
- **Next step: PR-E1 contract** (first tutoring session; closes V1). Not yet written — architect + developer sign-off required. After D1 merges, parallel implementers are enabled.

## 1. PR Contracts (delivered ones kept as review reference)

### PR-0 — Vertex fix *(DELIVERED: `fix/vertex-credentials-env`, pending merge)*

The working tree contains a real, tested fix (`api/credentials_service.py`, `open_notebook/ai/key_provider.py`, `open_notebook/ai/models.py`) that makes UI-entered Vertex AI credentials work. It must not stay uncommitted.

- Branch: `fix/vertex-credentials-env`
- Commit: `fix: mirror Vertex credentials into env vars so UI-entered credentials apply`
- Include the `CORE_CHANGES.md` entry in the same PR.
- Optional follow-up (developer's call): open the same fix as a PR to upstream OpenNotebook; if merged there, the core divergence disappears.
- Dogfood: enter a Vertex credential in the UI, test it, run a chat completion against a Vertex model.

### PR-A1 — Tutoring service skeleton *(Feature A; DELIVERED: `feature/a/skeleton`, pending merge)*

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

### PR-B1 — Multi-model layer *(Feature B; DELIVERED: `feature/b/llm-layer`, pending merge)*

**Decision:** the tutor gets its own small, typed LLM interface; the only implementation wraps **Esperanto** (already a repo dependency, same library OpenNotebook uses). Tutor code never imports `esperanto` outside the adapter file — if Esperanto is ever replaced, only the adapter is rewritten.

**Layout:**

```
tutor/llm/
  __init__.py
  interface.py   # ChatMessage, ChatResponse, LLMProvider (Protocol)
  esperanto.py   # EsperantoProvider adapter — the ONLY file that may import esperanto
  factory.py     # provider_from_env(settings) -> LLMProvider
  __main__.py    # dogfood CLI: `uv run python -m tutor.llm "prompt"`
```

**Interface (fixed):**

```python
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class ChatResponse(BaseModel):
    content: str
    provider: str
    model: str

class LLMProvider(Protocol):
    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse: ...
```

- Esperanto call surface (verified in `open_notebook/ai/`): `AIFactory.create_language(model_name=..., provider=...)`, `await model.achat_complete(messages=[{"role", "content"}])` → `.content`.
- Env vars (added to `.env.example`): `TUTOR_LLM_PROVIDER` (Esperanto provider id: `anthropic`, `openai`, `ollama`, `vertex`…), `TUTOR_LLM_MODEL`. API keys come from each provider's standard env vars, never new ones. Both settings live on `TutorSettings`.
- Tests: adapter with an injected fake Esperanto model (message conversion, empty-content handling); factory happy/error paths with `EsperantoProvider` monkeypatched. No network in tests.

**Usable when:** `uv run python -m tutor.llm "Say hi"` prints a model answer, and switching `TUTOR_LLM_PROVIDER`/`TUTOR_LLM_MODEL` alone (no code change) switches the provider.

### PR-C1 — Learner profile *(Feature C; DELIVERED: `feature/c/profile`, pending merge)*

**Decisions:** tutor data lives in a **separate SurrealDB database `atenea`** in the shared instance (same `SURREAL_URL`/credentials/namespace as OpenNotebook, different database) — zero collision with upstream's migration chain. Schema is applied **idempotently at service startup** (`DEFINE ... IF NOT EXISTS`); no migration framework until schema churn justifies one. Questionnaire is a **CLI wizard consuming the service API** (API-first preserved). Default user: `TUTOR_USER_ID`, default `juanda`.

**Layout:**

```
tutor/
  db.py                # async SurrealDB client for the atenea database; applies schema on connect
  schema.surrealql     # DEFINE TABLE/FIELD/INDEX IF NOT EXISTS for profile + session
  profile/
    __init__.py
    models.py          # Profile (Pydantic): user_id, learning_goal, self_assessed_level,
                       #   weekly_availability_hours, format_preferences, created, updated
    service.py         # get_profile(user_id), upsert_profile(profile)
    router.py          # GET /profile (404 if none), PUT /profile (upsert)
    __main__.py        # wizard: `uv run python -m tutor.profile` → 4 questions → PUT /profile
```

**Schema (fixed):** `profile` — `user_id: string` (unique index), `learning_goal: string`, `self_assessed_level: string`, `weekly_availability_hours: float`, `format_preferences: array<string>`, `created`/`updated: datetime`. `session` (defined now, used from PR-E1) — `user_id: string` (indexed), `started_at`/`ended_at`, `summary`, `assessment`, `next_step`, `review_date` (all optional except `user_id`, `started_at`).

- Env vars (added to `.env.example`): `TUTOR_SURREAL_DATABASE` (default `atenea`), `TUTOR_USER_ID` (default `juanda`); connection reuses `SURREAL_URL`/`SURREAL_USER`/`SURREAL_PASSWORD`/`SURREAL_NAMESPACE`.
- The `surrealdb` import stays contained in `tutor/db.py` (same pattern as the Esperanto adapter).
- Tests: service/router with a fake DB layer; wizard input parsing. No live SurrealDB in tests.

**Usable when:** with the stack up, `uv run python -m tutor.profile` completes the questionnaire, and `curl localhost:5056/profile` returns the stored profile (visible again after restarting the service).

### PR-D1 — Tool registry *(Feature D; DELIVERED: `feature/d/tool-registry`, pending merge)*

**Purpose:** uniform discover/call interface so new tutor capabilities are new registry entries, never surgery on the tutor (AGENTS.md rule #5). Descriptions are written for LLM consumption — PR-E1 will feed `list_specs()` into function calling.

**Layout:**

```
tutor/tools/
  __init__.py
  registry.py       # ToolSpec, ToolRegistry, UnknownToolError, DuplicateToolError
  content.py        # content.search → POST /api/search (via OpenNotebookClient.search)
  profile_tools.py  # profile.read / profile.write → ProfileService
  defaults.py       # build_default_registry(settings) wiring the three entries
  __main__.py       # dogfood CLI: `python -m tutor.tools [list]` / `call <name> '<json>'`
```

**Interface (fixed):**

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                      # namespaced: "content.search", "profile.read"...
    description: str               # LLM-facing
    input_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[Any]]   # receives the validated input_model

class ToolRegistry:
    def register(self, spec: ToolSpec) -> None          # DuplicateToolError on collision
    def get(self, name: str) -> ToolSpec                # UnknownToolError if absent
    def list_specs(self) -> list[dict]                  # name, description, input JSON schema
    async def call(self, name: str, arguments: dict) -> Any   # validates, then awaits handler
```

- Initial entries: `content.search` (`query`, `limit=10`, `type=text|vector`; ON search surface verified in `api/routers/search.py` + `api/models.py`), `profile.read` (no args → profile or null), `profile.write` (questionnaire fields → stored profile).
- `OpenNotebookClient` gains `search()`. No new env vars.
- Tests: registry semantics (duplicate, unknown, validation), each tool with fakes, default wiring lists all three. No network/DB in tests.

**Usable when:** with the stack up, `uv run python -m tutor.tools` lists the three entries and `uv run python -m tutor.tools call content.search '{"query": "<something indexed>"}'` returns results; `profile.read`/`profile.write` round-trip works.

**Merging PR-D1 enables parallel implementers** (stable interfaces exist: data layer, LLM layer, tool registry).

### PR-E1 — First tutoring session *(Feature E; contract fixed, signed off 2026-07-12; closes V1)*

**Decisions (developer, 2026-07-12):** the fixed "2 attempts before answer" rule is **replaced by a graduated-help policy** (see below) — the fixed threshold lacked research support (worked-example effect, assistance dilemma) while generation-first + graduated hints is well grounded (generation effect, pretesting, faded worked examples). Traits are **classified by the tutor LLM** at session open (logged, conversationally correctable). Tutor **replies in the learner's language** (prompts in English). **No CLI chat**: E1 ships endpoints verified via curl; **PR-F1 follows immediately** with a minimal chat page served by the tutor service itself (plain HTML+JS consuming the API; OpenNotebook's Next.js frontend untouched).

**Layout:**

```
tutor/session/
  __init__.py
  models.py      # ContentTraits, TechniquePlan, HelpState, SessionState, API models
  techniques.py  # select_technique(traits, level) -> TechniquePlan  (pure, unit-tested)
  policy.py      # graduated-help ladder (pure)
  engine.py      # TutorEngine: open/message/close; LLM + registry injected
  router.py      # POST /session, POST /session/{id}/message, POST /session/{id}/close, GET /session/{id}
  store.py       # session persistence over tutor/db.py
tutor/prompts/   # session_system.md, classify_traits.md, close_summary.md (English)
```

**Technique mapping (fixed, composable):** production type picks the primary technique — `recall` → retrieval practice; `apply` → faded worked examples (novice) / problem-solving with feedback (intermediate+); `explain/transfer` → Socratic self-explanation. Verifiability modulates feedback (verifiable → immediate corrective; interpretive → criteria-based discussion). Structure modulates sequencing (hierarchical → prerequisites first; distributed → interleaving/connections).

**Graduated-help policy (fixed):** per-exercise state tracks `attempts` and `help_level` (0 none → 1 conceptual hint → 2 procedural hint → 3 partial solution → 4 full solution). Full solution only after the ladder is climbed or the learner explicitly gives up after ≥1 attempt; novice+apply sessions may start from worked examples. The engine injects attempts/help_level into the system prompt every turn — auditable in the session log, never dependent on LLM memory alone.

**Engine-orchestrated tools (V1):** the engine calls registry entries deterministically (open → `profile.read` + `content.search` on the topic; close → session write) and feeds results into prompts. LLM-driven function calling over `list_specs()` is a later enhancement, not V1.

**Session record:** extends `schema.surrealql` `session` table (append-only, idempotent) with `topic`, `traits` (flexible object), `technique`, `transcript` (flexible array). Transcript persisted after every turn. On close, the LLM produces summary, assessment, next step + review date.

- No new env vars. Tests: mapping and policy as pure functions; engine and router with fake LLM/registry/store. No network/DB/LLM in tests.

**Usable when:** with the stack up, profile created and material indexed — `curl POST /session {"topic": ...}` opens (returns traits + technique + opening message), a few `POST /session/{id}/message` exchanges hold a real (short) tutoring dialogue over the learner's own document, `POST /session/{id}/close` stores and returns a readable record (`GET /session/{id}`) with summary, assessment, next step, review date. **Merging PR-E1 closes V1.**

### PR-F1 — Minimal chat page *(Feature F; contract fixed 2026-07-12)*

- `tutor/ui/index.html`: one static file — vanilla HTML+CSS+JS, no framework, no build step. Served by the tutor service itself at `GET /` (root). Consumes only the public session endpoints; OpenNotebook's Next.js frontend untouched.
- Flow: enter topic → open session (traits + technique shown as badges) → chat turns (attempts / help level visible) → close (renders the stored record: summary, assessment, next step, review date).
- Friendly error states: 409 (no profile yet → points to the questionnaire), 503 (TUTOR_LLM_* unconfigured), network failures.
- Tests: `GET /` serves the page (200, HTML, contains app markup). The JS itself is intentionally untested in V1 — single file, validated by dogfood; a JS test harness is not worth its weight yet.

**Usable when:** a full E1 session (open → dialogue → close) happens in the browser at `http://localhost:5056/` without curl.

### PR-DX1 — One-command startup *(contract fixed 2026-07-12, signed off by the developer)*

- `Dockerfile.tutor` (new, repo root): slim two-stage image — `python:3.12-slim-trixie` + uv, `uv sync --frozen --no-dev` against the repo's shared lockfile (no dependency drift vs. OpenNotebook), copies only `tutor/`, `CMD python -m tutor`, `EXPOSE 5056`, container healthcheck via `GET /health`. No Node, no frontend build (unlike the upstream `Dockerfile`).
- `docker-compose.yml`: new `tutor` service appended — built from `Dockerfile.tutor`, port `5056:5056`, `depends_on: [surrealdb, open_notebook]`, `restart: always`. Compose pins service-to-service URLs (`SURREAL_URL=ws://surrealdb:8000/rpc`, `OPEN_NOTEBOOK_API_URL=http://open_notebook:5055`) in the `environment` section, which takes precedence over `env_file`. LLM provider keys and `TUTOR_*` settings arrive via `env_file: .env` with `required: false` — the same file `make tutor` loads in dev (decision: zero duplication over a minimal explicit variable list). Existing services untouched.
- Tests (`tests_tutor/test_compose.py`): parse `docker-compose.yml` and assert the tutor service exists, builds from `Dockerfile.tutor`, exposes 5056, pins the two service URLs, reads the optional env_file, and depends on both services. Guards drift without requiring Docker in CI.
- `CORE_CHANGES.md`: one entry (`docker-compose.yml` edited, `Dockerfile.tutor` added — both outside `tutor/`).
- `.env.example`: note that compose passes `.env` to the tutor container. Zero Python code changes.

**Usable when:** cold machine → `cp .env.example .env` (set `TUTOR_LLM_*` + provider key) → `docker compose up -d` → full session in the browser at `http://localhost:5056/`. `make tutor` keeps working for dev.

### PR-E2 — Session quality *(contract fixed 2026-07-12, signed off; evidence base: `docs/atenea/tutor_pedagogy_evidence.md`)*

Two halves.

**(a) Per-task state.** The session prompt makes the tutor open each NEW task with a line `[[TASK: short label]]`. `tutor/session/markers.py` parses it (`parse_task_marker`), strips it from the learner-facing text, and keeps the raw reply (marker included) in the transcript so the model sees its own boundaries. `SessionState.task: TaskState{index, label}` persists in the store; on a new marker the engine bumps `index` and resets `HelpState` (attempts + help_level reset per task). `MessageResponse`/`SessionOpenResponse` expose `task_index` + `task_label`; the UI shows `tarea N · "label" · intento K · ayuda L/4`. No marker ever ⇒ implicit task 0, pre-E2 behavior (nothing breaks).

**(b) Evidence-based prompt-evaluation loop.** `tutor/eval/`: 4 scripted (deterministic, no LLM-learner) personas in `tutor/eval/personas/*.json` — novice-stuck, advanced-correct, stable-misconception, adversarial-pushback — each carrying ground-truth error annotations. The runner replays each persona through the REAL `TutorEngine` + real tutor LLM with in-memory fakes for registry/store (no SurrealDB, no OpenNotebook). A judge (`tutor/prompts/judge_rubric.md`) scores 10 evidence-derived criteria (learner-does-work, error-flagging, contingent-help both directions, uptake, praise-discipline, actionability, calibration, real-checks, non-sycophancy, session-close), ONE criterion per call, reference-anchored to the annotations. Programmatic no-LLM metrics (word ratios, turn length, praise/pseudo-check counts) run alongside as bias-immune signals. `TUTOR_JUDGE_PROVIDER/MODEL` selects the judge (default = tutor's; runner warns on same-family). `make eval-tutor` writes `eval_runs/<ts>.json` (gitignored) + a console table.

**(c) Master prompt v2.** `session_system.md` rewritten from the same evidence (contingency both ways, mandatory uptake, attempt-before-explanation on tractable tasks, no pre-emptive error warnings, banned "¿tiene sentido?", learner-produced close with if-then next step).

Tests: marker parsing, per-task reset in the engine, persona loading, judge-prompt render, judge-JSON parse, metrics, full runner end-to-end (all offline with injected fakes). `CORE_CHANGES.md` entry for `Makefile` + `.gitignore` (outside `tutor/`).

**Usable when:** (a) in a real browser session the UI shows task/attempt/help that reset when the tutor moves to the next task; (b) `make eval-tutor` produces a report scoring the 10 criteria across the 4 personas; (c) editing `session_system.md` and re-running measurably moves the scores (v1 vs v2 comparison is part of dogfood).

## 1.5 First Live Dogfood — Findings (2026-07-12, session on "aprender a aprender")

V1 works end-to-end (profile → open → dialogue → close). Quality failures observed and their disposition:

- **Interrogation without instruction** — the tutor chained questions for 6 turns without ever teaching or proposing a plan. Cause: prompt over-weighted "make the learner generate". *Fixed in prompt*: mandatory session plan in the opening, teach-then-check structure every turn, gap-closing before advancing.
- **Per-turn flattery** ("Excelente", "muy agudo"). *Fixed in prompt*: praise banned except once per session for substance.
- **`attempts` counts messages, not attempts on a task** — misleading. *Mitigated*: UI no longer shows it (help level only, when > 0). *Real fix is backlog*: per-exercise state machine (tutor signals task boundaries; attempts/help reset per task). Candidate PR-E2.
- **Backlog reinforced**: the pedagogical-prompt layer needs its own iteration loop (the LLM-judge eval harness already deferred in `atenea_context.md` §2); a prompts-quality PR should not wait for the learned-selection version.

Lesson for future implementers: prompt constraints are followed literally — always pair a "do X" with its failure-mode counterweight ("but never Y").

A second session after the prompt rewrite showed **substantial improvement, still short of target** (developer's judgment, 2026-07-12). Session quality is now the top deferred work item — see the post-V1 queue below.

## 1.6 Post-V1 Queue (decided 2026-07-12, supersedes backlog order until done)

Rationale: the felt value of Atenea lives in session quality, and the dogfooding loop dies if startup friction stays high (developer's working profile: high activation cost). Features G/H/I wait.

1. **Merge the delivered chain** (PR-0 → A1 → B1 → C1 → D1 → E1 → F1), in order. Closes V1, enables parallel implementers. Then revoke the GitHub PAT and rotate the DeepSeek key used during the 2026-07-12 session.
2. **PR-DX1 — one-command startup.** Add the tutor as a service in `docker-compose.yml` (image built from the repo; env passed like the open_notebook service) so `docker compose up -d` brings up SurrealDB + OpenNotebook API + tutor together; keep `make tutor` for dev. Usable when: from a cold machine, `docker compose up -d` + browser = working session. Contract fixed in §1 above (2026-07-12).
3. **PR-E2 — session quality.** Two halves: (a) per-task state — the tutor marks task boundaries (structured marker in its replies, parsed by the engine); attempts/help_level reset per task and the UI shows them per task honestly; (b) first prompt-evaluation loop — a small set of scripted learner personas + an LLM-judge rubric (teaches-before-asking, no flattery, plan adherence, help-ladder compliance) run against prompt changes, so pedagogy iterates on measurement. This pulls forward part of the deferred "learned selection" work without the fine-tuning half.
4. Then resume the ordered backlog (Feature G onward) in `atenea_pr_plan.md`.

Additional deferred observation (developer, 2026-07-12): **the tutor and OpenNotebook feel like two separate apps** — different UIs, different UX, different ports; today's integration is content-only (search over indexed sources). A unified experience (single entry point; either the tutor embedded in OpenNotebook's UI or OpenNotebook's library views embedded in the tutor's) plus a real visual pass on the tutor UI is **Feature F2** territory: registered in the backlog, deliberately after DX1/E2 — it's part of the "deep visual frontend rework" the context doc already defers, now with a sharper definition of what hurts.

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

Extension before modification (log exceptions in `CORE_CHANGES.md`) · API-first · `user_id` everywhere · config via env only · tools only via the registry (from Feature D) · one PR = one dogfoodable slice · tests mandatory · LF line endings · English in repo · open product decisions belong to the developer.
