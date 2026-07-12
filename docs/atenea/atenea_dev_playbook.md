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

### Then: PR-C1 → PR-D1 → PR-E1 (V1), per `atenea_pr_plan.md`

Contracts for C1 onward are **not yet written**. Architect step required before each: write the contract into §1 of this playbook (interface signatures, env vars, schemas), get developer sign-off, then hand to an implementer. Serial until Feature D is merged.

## 2. CI Policy

- Upstream `test.yml` covers OpenNotebook. PR-A1 must extend CI so every PR also runs `make check-tutor` (same workflow file, extra job — document it in `CORE_CHANGES.md` only if upstream's wor