# Atenea — Development Playbook (v1)

> Operational plan for agents continuing development. Read *after* `atenea_context.md`, `atenea_pr_plan.md`, and `AGENTS.md`. This document contains: the current state, the next PR contracts, and the recurring checklists (review, CI, upstream sync). Architects update it when contracts change; implementers never edit contracts here.

## 0. Current State (updated 2026-07-14, end of day — everything integrated)

- Fork of OpenNotebook at `open-notebook/`. **Everything delivered so far is merged to `main`** (one merge commit per PR): PR-0 + Features A–F (= V1 narrative label, 2026-07-12), DX1, E2, F2 (+dogfood fixes), R1, H1, G1, M1, the §4 upstream sync (upstream @7dfe8aa, migrations 19–22, security hardening — see §1.9 notes if present or CORE_CHANGES.md), DX2, F3, and M2.
- **Feature M complete through M2:** sessions can be anchored to a chosen source; since M2, retrieval ranks DB-side *within* the source (migration 23 adds optional `$source_id` to `fn::vector_search`; tutor keeps a client-side filter as defense-in-depth). Second core divergence after PR-0 — both logged in `CORE_CHANGES.md` with revert recipes.
- **PR-G2 merged 2026-07-18** (@2dbc60d): consolidated learner memory (`learner_memory` LTM tier, verified consolidation with verifier-as-regenerator, recall at open, "Tu progreso" view). One audit fix before merge: contract v1 degenerated merge into single-episode overwrite — amended so the generator integrates prior note content and the verifier admits it as evidence (regression-locked by test; see §1 PR-G2 audit note).
- **Verification state:** 130 tutor tests + `make smoke` (14-step fake-LLM journey, <1s, zero keys) + ruff + mypy green on `main`. **Pending on the developer:** live-stack validation of migration 23 + real grounded search (`TUTOR_SMOKE_BASE_URL` run or a browser session on an indexed source), and a milestone browser dogfood.
- What runs today: `docker compose up -d --build` = SurrealDB + OpenNotebook (8502/5055) + tutor (5056: chat UI, profile questionnaire, source picker, resume, history, review loop). Dev loop: `make tutor-dev` / `make tutor-restart`; instant check: `make smoke`; full gate: `make check-tutor`. Eval: `make eval-tutor`.
- Decisions fixed: tutor service in **`tutor/`**; Python **3.12** via `uv`; tutor data in separate **`atenea`** database (shared SurrealDB instance); `TUTOR_USER_ID` (default `juanda`); LLM access only via the tutor's interface wrapping **Esperanto** (plus the deterministic `fake` provider for smoke); judge LLM should differ in provider family from the tutor; repo name stays `open-notebook` (rename = open decision).
- Credentials (developer decision 2026-07-12): existing GitHub PAT + DeepSeek key stay in use; rotation waived. `upstream` remote configured (lfnovo/open-notebook).
- **Push to origin verified done (2026-07-18):** `main` @ `c22483a` in sync with `origin/main`. Still pending on the developer: CI result of the first pushed run, live-stack validation of migration 23, milestone browser dogfood.
- **Next queue:** PR-G3 (contract signed off 2026-07-19, §1 — completes Feature G; milestone dogfood follows), then M-coverage / M-tasks slices, Features T (runtime tool creation), V (voice), and W (LLM output verification layer — registered 2026-07-18, needs a SOTA note before contracting; G2 shipped its first fenced instance) registered unordered. **Sequencing rule (developer, 2026-07-19):** nothing that *consumes* learner-memory content (K/tree, memory-informed M-tasks) gets contracted until the developer has dogfooded Feature G. Contracts per the standing protocol (architect pins facts → Sonnet implements → architect audits).
- **New agent conversation? Start with §6 (Handoff Protocol).**

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

### PR-F2 — Unified experience *(contract fixed 2026-07-12, signed off by the developer)*

Tutor-first unification: the tutor UI is the single entry point; OpenNotebook stays untouched (its deep frontend rework remains deferred — F2 paves the road for it and for daily dogfooding).

- `GET /config` (new endpoint): minimal JSON with `notebook_ui_url` (env `TUTOR_NOTEBOOK_UI_URL`, default `http://localhost:8502`). The chat page's header gains a "Notebooks ↗" link pointing there — no port memorization; link hidden if /config fails.
- Visual pass on `tutor/ui/index.html` (still one static file, vanilla, no build step, no CDN): Atenea identity v1 as documented CSS design tokens (night blue + gold-olive, "refined dark" — chosen for future lift into the rework); ~40-line escape-first markdown mini-renderer for tutor replies (headings, lists, bold/italic/code, fenced blocks, blockquotes); typing indicator; restyled task·attempt·help chips (E2) and closing record; friendly 409/503/network errors; responsive; Spanish-first copy.
- Tests: `/config` default + settings override; `GET /` contains nav link, `/config` reference and the markdown renderer. Page JS itself stays untested (F1 criterion).
- No `CORE_CHANGES.md` entry (nothing outside `tutor/` + docs except `.env.example`, names only).

**Usable when:** a full session at `http://localhost:5056/` reads well (markdown, per-task chips, record) and you can jump to OpenNotebook from the header without remembering ports.

### PR-R1 — Session resume *(signed off; implemented + committed @ `c8a0fa2`, pending developer dogfood + merge)*

Problem (live dogfood, 2026-07-12): abandoning the chat page orphans an open session. The state is NOT lost server-side — every turn is persisted (`session` table, `store.save_progress`, and `engine.message()` rehydrates from the store by id) — but nothing lists open sessions and the client forgets `session_id`, so the session is unreachable and dogfooding restarts from zero.

- `GET /sessions?status=open|closed` (new endpoint): the user's sessions — id, topic, status, last-update timestamp, task/help snapshot. Scoped by `user_id` like everything else.
- `GET /session/{id}`: verify it returns open sessions with their transcript (not only close records); extend if needed so a client can re-render the whole conversation.
- UI resume path: on page load, fetch open sessions; if any exist, offer "Continuar" (most recent, with topic + when) next to starting a new one; replay the transcript through the same markdown renderer; keep the session id in the URL hash (`#s=<id>`) so refresh/bookmark resumes. No localStorage — state stays server-derived.
- Service-restart proof: resuming must work purely from the store (it already should — this is a test to write, not new code).
- Out of scope: auto-closing stale sessions, multi-device sync UX (list + resume is the slice).
- Tests: list endpoint scoping/shape/status filter, transcript replay on `GET /session/{id}` for an open session, resume-after-restart (fresh engine instance over the same store), UI markup markers for the resume affordance.

**Usable when:** close the tab mid-session, reopen `localhost:5056`, tap "Continuar" and the conversation is back exactly where it stopped — even after restarting the tutor service.

### PR-M — Material-grounded sessions *(signed off 2026-07-14; PR-M1 merged; PR-M2 merged @ 0f10159 (2026-07-14). Higher-risk PR, change surface delimited below)*

Problem: today `engine.open` grounds a session in a lossy search digest (`_content_digest`: top-5 hits, 300-char snippets) — the tutor teaches *around* the topic, not *from* a chosen text, cannot cite back, and cannot track how much of a source has been worked. OpenNotebook already ships the RAG substrate (embeddings, chunked `fn::vector_search`, `ContextBuilder`, token budgeting); Feature M is about *consuming* it from the tutor over REST, not rebuilding it.

**Delimitation (applies to every M slice — higher-risk feature, so the change surface is fenced for review + revert):**
- **One seam.** All grounding lives in a new module `tutor/session/grounding.py` exposing one function `retrieve_grounding(source_id, query) -> GroundingContext`. `engine.open`/`engine.message` call it in exactly one place each — the only edits to `engine.py`. Removing the call reverts the feature.
- **Opt-in, additive.** No `source_id` ⇒ byte-for-byte the current digest path (backward-compat test locks it). Gated behind config `TUTOR_GROUNDING_ENABLED` (dogfood off-switch).
- **Stable interface across M1→M2.** `retrieve_grounding`'s signature is fixed; the M1→M2 change swaps only its internals — engine + tests stay put.
- **Persistence:** one new nullable field `source_id` on the tutor's `session` table (atenea DB), additive; it is what lets PR-R1 resume keep the anchor.

**PR-M1 — Anchor retrieval to a chosen source (tutor-side, zero core changes).** New OpenNotebook REST client method + `content.search` gains an optional `source_id`; `retrieve_grounding` over-fetches the existing global vector search (`POST /api/search`, `type=vector`, generous `limit`) and filters rows to `parent_id == source:{id}` on the tutor side — every `fn::vector_search` row already carries `parent_id`. The engine feeds the retrieved, source-scoped chunks (with source refs) into the pedagogy prompt, which is told to cite back into the source. UI: pick a source at open (list via `GET /api/sources`, optionally scoped by notebook); no source = today's behavior. **Hard invariant: the M1 diff touches only `tutor/` — zero edits under `open_notebook/`, `api/`, `migrations/`** (a reviewer verifies M1 by confirming the diff is `tutor/`-only). Accepted limitation: approximate scoping — if the source's relevant chunks rank low globally, raise `limit`; the real fix is M2. Tests: client method shape; `retrieve_grounding` filters by source over a fake search; engine grounds the prompt in source chunks; `source_id` persists + rehydrates on resume; no-source path unchanged; UI selector markup. **Usable when:** you open a session on a chosen document and the tutor teaches from that document, quoting it — and it survives a resume.

**PR-M2 — Source-scoped vector search in core (fenced core change; sequenced AFTER the §4 upstream sync).** Swap `retrieve_grounding`'s internals to a real DB-side source filter — engine and M1 tests unchanged. Core touch confined to four files, each logged in `CORE_CHANGES.md` with a revert note: (1) a NEW additive migration (next number) adding an optional source-filter param to `fn::vector_search` via the existing `REMOVE + DEFINE` pattern, with its `_down`; (2) `open_notebook/domain/notebook.py::vector_search` — new optional param, default preserves today's behavior; (3) `api/models.py::SearchRequest` — optional `source_id`/`notebook_id`; (4) `api/routers/search.py` — thread it through. This is the tutor's *first* modification to OpenNotebook's own migration chain (until now the tutor lives in a separate `atenea` DB precisely to avoid this), so it lands deliberately and only after §4's sync merge is in — never stacking conflict surface on that already-fragile merge. **Usable when:** grounding stays sharp on large sources because retrieval is ranked DB-side within the chosen source.

**Registered, later M slices (no contract yet — after M1/M2 dogfood):** *M-coverage* — represent the source as sections/chunks, tutor marks worked ones (`[[COVERED: …]]`, same pattern as E2's `[[TASK:]]`), persist + show % covered. *M-tasks* — derive tasks from the source's sections (walk the material in order) instead of improvising around the topic. Both build on M1's anchor. Out of scope for M entirely: multi-source sessions (one source first), re-indexing/embedding, auto-selecting material (that is J/K).

### PR-H1 — Session & progress tracking view *(signed off 2026-07-14; implemented @ `7f4c619` on `feature/h/tracking` — autonomous, pending review; read-only surface, no core/schema)*

A dedicated history/progress view over already-stored session data — no new model (`atenea_pr_plan.md` H = "surface, not a new model"). Complements PR-R1: R1's setup panel offers *resume* of open sessions; PR-H1 surfaces the *review* side — closed sessions and what is due to revisit.

Delimitation: read-only and additive. No writes, no schema change, no store change beyond reading fields already persisted; the one API change is an optional `review_date` on each `SessionSummary` row (written at close since PR-E1, just now surfaced). Diff confined to `tutor/` + `tests_tutor/` — zero edits under `open_notebook/`, `api/`, `migrations/`.

- `GET /sessions` (PR-R1) rows gain `review_date` (mapped from the record; null for open sessions).
- UI "Historial y progreso" (header link) groups the user's sessions: **Para repasar** (closed + `review_date` due now, computed client-side), **Abiertas**, **Completadas**; each row opens the stored session via the existing `GET /session/{id}` and the shared markdown renderer.
- Out of scope: SM-2 scheduling (that is Feature G — H only surfaces the `review_date` already written at close), editing/deleting sessions, cross-session analytics.
- Tests: summary carries `review_date` for closed / null for open; UI history markup. **Usable when:** open the Historial link and see your past sessions grouped, with what is due for review, and click through to any of them.

### PR-G1 — Cross-session review loop *(signed off 2026-07-14; implemented @ `ad899f0` on `feature/g/review` — autonomous, pending review; additive, tutor DB, no core)*

First slice of Feature G = **cross-session memory**, not "just SM-2" (`atenea_context.md`: spaced repetition is one technique among several; `tutor_pedagogy_evidence.md`: "cross-session memory injection — Feature G territory"). This slice is the review/resurfacing loop with a three-part memory lifecycle:
- **Inject:** `engine.open_review` pulls the learner's due prior sessions (closed, `review_date` <= now) and injects their summary / assessment / unfinished next_step into a review-mode session, interleaving up to 3 (`review_system.md`: retrieval-first, relearn-to-criterion — Rawson & Dunlosky 2022, Rohrer 2020).
- **Update:** on close, covered items' `review_date` is pushed out (crude reschedule — reuses the close's `review_in_days`).
- **Evict:** after `GRADUATION_REVIEWS` (3) reviews an item's `review_date` is cleared — it leaves the review working-set efficiently; the session record itself stays for history (H1's "Completadas"), so the progress summary is retained, not deleted.

Delimitation: additive; two new tutor-DB fields (`reviewed_ids`, `review_count`), `GET /reviews/due` + `POST /review`, a UI "Repasar lo pendiente" entry, `review_system.md`. Due filtering runs in Python (no fragile null/date SurrealQL). Diff confined to `tutor/` + `tests_tutor/` — no core.

Open questions for review (developer, 2026-07-14): (a) the graduation signal is count-based (crude) — should evict on *demonstrated* mastery, not a fixed count; (b) a **consolidated learner-memory** (a compact, durable "how far you've come" summary, distinct from per-session records) is the natural next step — **pending a SOTA review of agent memory management** before it is designed. Registered as PR-G2+.

Tests: due filtering/scoping/order; memory injection into the review prompt; reschedule vs graduation-evict; `/reviews` endpoints; review prompt is retrieval-first + interleaving. **Usable when:** when material is due, "Repasar lo pendiente (N)" starts a session that revisits your prior sessions from memory, and mastered items drop out of the queue.

### PR-E2 — Session quality *(contract fixed 2026-07-12, signed off; evidence base: `docs/atenea/tutor_pedagogy_evidence.md`)*

Two halves.

**(a) Per-task state.** The session prompt makes the tutor open each NEW task with a line `[[TASK: short label]]`. `tutor/session/markers.py` parses it (`parse_task_marker`), strips it from the learner-facing text, and keeps the raw reply (marker included) in the transcript so the model sees its own boundaries. `SessionState.task: TaskState{index, label}` persists in the store; on a new marker the engine bumps `index` and resets `HelpState` (attempts + help_level reset per task). `MessageResponse`/`SessionOpenResponse` expose `task_index` + `task_label`; the UI shows `tarea N · "label" · intento K · ayuda L/4`. No marker ever ⇒ implicit task 0, pre-E2 behavior (nothing breaks).

**(b) Evidence-based prompt-evaluation loop.** `tutor/eval/`: 4 scripted (deterministic, no LLM-learner) personas in `tutor/eval/personas/*.json` — novice-stuck, advanced-correct, stable-misconception, adversarial-pushback — each carrying ground-truth error annotations. The runner replays each persona through the REAL `TutorEngine` + real tutor LLM with in-memory fakes for registry/store (no SurrealDB, no OpenNotebook). A judge (`tutor/prompts/judge_rubric.md`) scores 10 evidence-derived criteria (learner-does-work, error-flagging, contingent-help both directions, uptake, praise-discipline, actionability, calibration, real-checks, non-sycophancy, session-close), ONE criterion per call, reference-anchored to the annotations. Programmatic no-LLM metrics (word ratios, turn length, praise/pseudo-check counts) run alongside as bias-immune signals. `TUTOR_JUDGE_PROVIDER/MODEL` selects the judge (default = tutor's; runner warns on same-family). `make eval-tutor` writes `eval_runs/<ts>.json` (gitignored) + a console table.

**(c) Master prompt v2.** `session_system.md` rewritten from the same evidence (contingency both ways, mandatory uptake, attempt-before-explanation on tractable tasks, no pre-emptive error warnings, banned "¿tiene sentido?", learner-produced close with if-then next step).

Tests: marker parsing, per-task reset in the engine, persona loading, judge-prompt render, judge-JSON parse, metrics, full runner end-to-end (all offline with injected fakes). `CORE_CHANGES.md` entry for `Makefile` + `.gitignore` (outside `tutor/`).

**Usable when:** (a) in a real browser session the UI shows task/attempt/help that reset when the tutor moves to the next task; (b) `make eval-tutor` produces a report scoring the 10 criteria across the 4 personas; (c) editing `session_system.md` and re-running measurably moves the scores (v1 vs v2 comparison is part of dogfood).


### PR-DX2 — Fast test & dev loop *(contract fixed 2026-07-14; testing delegated to agents by the developer)*

- `tutor/llm/fake.py`: deterministic `fake` provider (`TUTOR_LLM_PROVIDER=fake`) — no network, no keys: fixed traits from classify, scripted session replies (including a `[[TASK: ...]]` marker and a help-ladder response), schema-valid close JSON. Registered via the existing factory; esperanto untouched.
- `make smoke`: one command driving the FULL user journey over HTTP against an in-process app (TestClient) by default, or against a running stack if `TUTOR_SMOKE_BASE_URL` is set: health → create profile → empty list → open session (fake LLM, with and without `source_id`) → 2 messages → tracking view → close → list shows closed → review due → reopen record. Asserts codes + shapes; runs < 30s, zero config, zero keys.
- `make dev` / `make restart`: single-command local loop — `dev` = SurrealDB (compose) + tutor with auto-reload (`uvicorn --reload`); `restart` = restart only the tutor process/container. Documented at the top of the Makefile section.
- CI: smoke (in-process mode) added to the tutor CI job.

**Usable when:** on a cold machine, `make smoke` passes end-to-end with no configuration; during dev, one command restarts the loop.

### PR-F3 — UI completeness for dogfood *(contract fixed 2026-07-14)*

- First-run profile: if `/session` answers 409, the UI opens an in-page questionnaire (mirroring the `PUT /profile` model: goal, self-assessed level, weekly availability, format preferences) instead of a dead end; a "Perfil" nav item allows editing later.
- Grounding picker: `/config` gains `grounding_enabled`; when true, populate the existing `#source` select from the sources list (add a thin tutor-side `GET /sources` proxy to OpenNotebook if M1 didn't ship one); hidden when disabled.
- Header shows the configured provider/model (extend `/config`), so the developer always knows which LLM is live.
- Empty/loading/error states polished; still one static vanilla file, no CDN.

**Usable when:** cold start → create profile in the browser → open a grounded or ungrounded session → review + history — all discoverable without curl.

### PR-G2 — Consolidated learner memory *(Feature G; contract signed off 2026-07-18; grounded in `docs/atenea/agent_memory_sota.md` §7)*

**Purpose.** Add the missing LTM tier: a compact, evolving, per-topic learner model (`learner_memory`), consolidated at session close (reflection) and recalled at session open — the durable "how far you've come" summary, distinct from per-session records. Agent-controlled (Letta-style), fully additive in the `atenea` DB, **zero core changes**.

**Slicing.** G2 = table + verified consolidate-on-close + recall-at-open + "Tu progreso" view. Retention-aware forgetting (SM-2/strength replacing G1's count-based `GRADUATION_REVIEWS`) is **PR-G3**, not here; G2 lays the `strength` field G3 will animate.

**Schema (additive, idempotent, `schema.surrealql`):** table `learner_memory` — `user_id: string` (indexed), `topic_key: string` (unique index on `(user_id, topic_key)`), `topic_label: string`, `summary: string`, `mastery_estimate: float` (0–1), `recurring_errors: array<string>`, `strength: float DEFAULT 1.0` (reserved for G3), `sessions_count: int DEFAULT 0`, `last_session_id: option<string>`, `created`/`updated: datetime`.

**One seam — new module `tutor/session/memory.py`, exactly two functions:**
- `recall(store, user_id, topic, enabled) -> LearnerMemoryContext` — the topic's note + up to 2 related notes (recency-ranked) for prompt injection; empty context if none/disabled.
- `consolidate(store, generator_llm, verifier_llm, state, close_record, enabled) -> None` — reflection with verification (below). **Non-fatal on any failure** (log + continue): a close is never lost to a bad reflection.

**Consolidation (LLM keying + local merge — developer decision 2026-07-18; amended 2026-07-18 post-audit):** prompt `consolidate_memory.md` receives the episode (topic, summary, assessment, transcript) plus a compact list of the user's existing notes **with their content** (`topic_key`, `topic_label`, current `summary`, `mastery_estimate`, `recurring_errors`, `sessions_count` — truncated summaries acceptable); returns JSON `{topic_key, topic_label, summary, mastery_estimate, recurring_errors}`. Existing key ⇒ merge/supersede: the returned note must **integrate the prior note with the new episode** (trajectory, resolved vs. persisting errors), never a single-episode overwrite — the prompt instructs this explicitly (upsert over that row, `sessions_count += 1`). New key ⇒ new note. Malformed JSON ⇒ deterministic fallback key (normalized session topic), un-merged episode summary. *Audit note: v1 of this contract passed only `{topic_key, topic_label}` pairs, which degenerated merge into overwrite — the LTM never accumulated. Caught in audit 2026-07-18 (flagged by the implementer); amended before merge.*

**Verification step (developer decision 2026-07-18 — first fenced instance of Feature W):** every consolidated note is claim-checked before persisting. Prompt `verify_memory.md` (verifier LLM): every claim in the note must be evidenced by the episode; returns `{verdict: "pass"|"fail", violations: [...]}`. On fail ⇒ regenerate ONCE with the **verifier acting as generator**, violations injected as constraints ⇒ re-verify ⇒ still fail ⇒ skip the write (log). Bounded cost: worst case 3 extra LLM calls, close-path only (per-turn verification of tutoring replies = Feature W, out of scope here). Verifier config: `TUTOR_VERIFIER_PROVIDER` / `TUTOR_VERIFIER_MODEL` (env; names in `.env.example`); unset ⇒ falls back to the tutor's own LLM (zero-key smoke keeps working); warn when verifier == generator (same pattern as E2's judge warning). Intent: verifier stronger than generator.

**Engine edits (three call sites, one line each):** `open` and `open_review` call `recall` and inject the note as a new system-prompt section in `session_system.md` / `review_system.md` (the learner's history on this topic — instruct the tutor to *use* it pedagogically, not recite it); `close` calls `consolidate` after `store.close` (review sessions consolidate too).

**Config:** `TUTOR_MEMORY_ENABLED` (default **true** — developer accepted; off-switch kept for debug). `.env.example` names only.

**API + UI:** `GET /memories` (user-scoped, recency-ordered). UI "Tu progreso" (header link): topic_label · mastery · recurring errors · last seen; Spanish-first copy.

**Fake provider:** deterministic consolidation JSON + pass verdict (plus a fail-then-pass fixture reachable in tests); `make smoke` gains 2 steps (close ⇒ `GET /memories` shows the note; second open on the same topic succeeds).

**Tests:** consolidate paths (new key / merge into existing / malformed-JSON fallback); verification paths (pass ⇒ write; fail ⇒ verifier-regenerated write; double-fail ⇒ no write, close record intact); recall injected into the system prompt; **disabled ⇒ byte-identical prompts** (backward-compat lock, M1-style); store CRUD + user scoping; `/memories` shape/scoping; UI markup marker; smoke extension. No network/DB/real LLM in tests.

**Delimitation:** diff confined to `tutor/` + `tests_tutor/` (+ `.env.example` names, `docs/atenea` mirror). Out of scope: retention-aware decay/eviction (PR-G3), per-turn verification (Feature W), KT/predicted-mastery step selection, memory graphs, changes to G1's due queue, embeddings over memories.

**Usable when:** after closing a session on a topic you've worked before, opening a new one has the tutor demonstrably pick up from your real history ("la última vez confundiste X con Y"), "Tu progreso" maps your mastered vs. weak topics — and a consolidation that fails verification never contaminates the record.

### PR-G3 — Retention-aware forgetting *(Feature G, final slice; contract signed off 2026-07-19; completes Feature G = milestone dogfood point)*

Replaces G1's crude forgetting (count-based `GRADUATION_REVIEWS=3` + flat `review_in_days` reschedule in `store.record_review`) with retention-aware scheduling (`agent_memory_sota.md` §7 rec 3). Additive; diff confined to `tutor/` + `tests_tutor/` (+ `.env.example` names, docs mirror).

- **SM-2 per reviewed item.** `session` gains optional `ease` (default 2.5) and `review_interval_days`. The review-session close JSON gains a per-reviewed-item **quality grade 0–5** (deterministic in the `fake` provider). Classic SM-2: q<3 ⇒ interval resets to 1 day + ease penalized; q≥3 ⇒ interval grows (1 → 6 → interval×ease) with the standard ease update. Malformed/missing grades ⇒ conservative default q=3, clamped to [0,5] — never evict on a parse error. No LLM verification here (W applies to content, not bounded scalars).
- **Eviction by horizon, not count.** `GRADUATION_REVIEWS` is removed: an item leaves the review working-set when its next interval exceeds `TUTOR_REVIEW_HORIZON_DAYS` (env, default 60). Record stays for history, as today.
- **Visible decay.** `learner_memory.strength` (reserved by G2) updates on each topic consolidation (rises with successful sessions/reviews). `GET /memories` and "Tu progreso" show **estimated retention** = mastery × Ebbinghaus decay over time since `last_seen` — computed at read time by a pure function.
- **One seam:** new module `tutor/session/scheduling.py` with pure functions `sm2_next(ease, interval, quality)` and `retention(mastery, strength, elapsed)`, table-unit-tested. Called from existing sites only: `close` (grades), `record_review` (evolved signature), `/memories` read path.
- **Compat:** pre-G3 sessions without `ease`/`interval` get defaults on first review (interval seeded from their `review_in_days`). No core changes, no OpenNotebook migrations.
- **Tests:** SM-2 tables (progression, penalty, reset); grade parse/fallback; horizon eviction; retention math; pre-G3 compat; endpoint/UI markers; smoke extension.

**Usable when:** an item you nail moves out (6d → 15d → …) and eventually leaves the queue by interval; one you fumble comes back tomorrow; "Tu progreso" shows retention decaying since the last review.

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

1. ✅ **Merge the delivered chain** (PR-0 → A1 → B1 → C1 → D1 → E1 → F1), in order. Closes V1, enables parallel implementers. *Credentials decision (developer, 2026-07-12): the GitHub PAT and DeepSeek key stay in use — rotation waived, risk accepted after review. Push to origin is therefore unblocked (`main` is ~26 commits ahead).*
2. ✅ *(merged 2026-07-12)* **PR-DX1 — one-command startup.** Add the tutor as a service in `docker-compose.yml` (image built from the repo; env passed like the open_notebook service) so `docker compose up -d` brings up SurrealDB + OpenNotebook API + tutor together; keep `make tutor` for dev. Usable when: from a cold machine, `docker compose up -d` + browser = working session. Contract fixed in §1 above (2026-07-12).
3. ✅ *(merged 2026-07-12)* **PR-E2 — session quality.** Two halves: (a) per-task state — the tutor marks task boundaries (structured marker in its replies, parsed by the engine); attempts/help_level reset per task and the UI shows them per task honestly; (b) first prompt-evaluation loop — a small set of scripted learner personas + an LLM-judge rubric (teaches-before-asking, no flattery, plan adherence, help-ladder compliance) run against prompt changes, so pedagogy iterates on measurement. This pulls forward part of the deferred "learned selection" work without the fine-tuning half.
4. **PR-F2 — unified experience.** ✅ delivered (`feature/f2/unified-ux` @ `166199f`); pending developer dogfood sign-off + merge. Contract in §1.
5. **PR-R1 — session resume.** Contract proposed in §1 (pending sign-off). Prioritized here because session loss kills the dogfooding loop (§1.7) — same rationale that pulled DX1 forward.
6. Then resume the ordered backlog (Feature G onward, plus the registered-unordered features M/T/V) in `atenea_pr_plan.md`.

Additional deferred observation (developer, 2026-07-12): **the tutor and OpenNotebook feel like two separate apps** — different UIs, different UX, different ports; today's integration is content-only (search over indexed sources). A unified experience (single entry point; either the tutor embedded in OpenNotebook's UI or OpenNotebook's library views embedded in the tutor's) plus a real visual pass on the tutor UI is **Feature F2** territory: registered in the backlog, deliberately after DX1/E2 — it's part of the "deep visual frontend rework" the context doc already defers, now with a sharper definition of what hurts.

## 1.7 Third Dogfood Findings (2026-07-12, post-F2 delivery)

- **Abandoned sessions are unreachable** — leaving the page mid-session loses the conversation from the user's point of view. Root cause is client-side only: state is fully persisted per turn, but there is no open-session listing and the UI forgets `session_id`. *Fix registered as PR-R1* (contract in §1, pending sign-off) and prioritized right after F2 merges: session loss kills the dogfooding loop, same rationale as DX1.
- Not yet started (registered in `atenea_pr_plan.md` so handoffs never lose them): material-grounded sessions (M), knowledge tree (K, already in backlog), runtime tool creation (T), voice (V). Step by step — the developer prioritizes.

## 1.8 V1 Review Policy (developer decision, 2026-07-14)

Until V1 wraps: merges gate on **green checks + the automated smoke journey (PR-DX2)** instead of per-PR developer dogfood. Rationale (developer): manual multi-process restarts are high friction for someone learning the stack and needing production speed, and the UI lacks enough surface for meaningful dogfood. The developer dogfoods at milestones instead. **This policy holds until the developer revokes it** (intended for this early phase; V1 as a narrative label closed 2026-07-12) — after that, versions return to strict per-PR developer review ("no me puedo dar el lujo de no mirar muy de cerca").

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

## 6. Conversation Handoff Protocol (new agent conversations)

Agent conversations end (usage limits, context limits); the project must not lose the thread. A new architect/implementer conversation resumes like this:

1. **Read, in order:** `AGENTS.md` → `atenea_context.md` → `atenea_pr_plan.md` (backlog + Status) → this playbook (§1.6 queue, the last contracts in §1, and the latest findings section). The `context_files/` copies are canonical; `docs/atenea/` is the in-repo mirror — keep both in sync when editing either.
2. **Verify reality against the docs:** `git log --oneline -8` on `main` and open feature branches; `git status` must be clean before starting. Parallel conversations happen — trust git over your assumptions, and re-read Status if they disagree.
3. **Baseline before touching anything:** run the check suite and confirm it's green. Canonical: `make check-tutor`. In the Cowork Linux sandbox (no Docker, no Python 3.12; GitHub releases blocked for uv): `pip install --break-system-packages ruff mypy pytest fastapi httpx pydantic uvicorn python-dotenv pyyaml`, then run `pytest tests_tutor` / `ruff format --check` / `ruff check` / `mypy` with system python3.10. Set git author per commit: `git -c user.name="Juan Da" -c user.email="dalralik@gmail.com" commit`.
4. **Cowork sandbox quirks** (skip if not applicable): the mount can serve stale/truncated file views after Windows-side writes — parse-verify changed files before committing, prefer Linux-side heredoc rewrites for edits, rename-cycle (`mv x tmp && mv tmp x`) refreshes the cache; stale git lock/ref files may need the file-delete permission tool. Never embed raw NUL bytes in source (git flags the file binary) — use printable escapes (e.g. `\u0000` in JS).
5. **Then work the queue (§1.6):** next item → architect writes/updates the contract in §1 → **developer signs off** → implement on a `feature/<x>/<slug>` branch → checks green → developer dogfoods → merge (one merge commit per PR) → update Status here and in `atenea_pr_plan.md`.
6. **Contracts are law** (AGENTS.md): implementers never renegotiate scope mid-PR; open product decisions belong to the developer. When in doubt, ask the developer — a one-line question is cheaper than a wrong slice.

