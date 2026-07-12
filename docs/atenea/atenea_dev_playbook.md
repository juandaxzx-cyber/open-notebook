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

### PR-B1 — Multi-model layer *(Feature B; contract fixed, signed off 2026-07-12)*

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

### PR-C1 — Learner profile *(Feature C; contract fixed, signed off 2026-07-12)*

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

### PR-D1 — Tool registry *(Feature D; contract fixed 2026-07-12, sign-off = PR review)*

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

### Then: PR-E1 (V1), per `atenea_pr_plan.md`

Contract **not yet written**. Architect step required: write it into §1 (session flow, technique mapping, prompts location, session-record schema already in schema.surrealql), developer sign-off, then implement.

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
