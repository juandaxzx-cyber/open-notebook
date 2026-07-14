"""PR-M1 — material-grounded sessions (tutor-side, zero core changes)."""

import asyncio
from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tutor.app import create_app
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session.engine import TutorEngine
from tutor.session.grounding import retrieve_grounding
from tutor.session.models import SessionState
from tutor.session.store import SessionStore, UnknownSessionError
from tutor.tools.content import content_search_tool
from tutor.tools.registry import ToolRegistry, ToolSpec

CLASSIFY = (
    '{"verifiability": "verifiable", "structure": "hierarchical", '
    '"production": "apply"}'
)

_ROWS = [
    {
        "title": "Algebra",
        "content": "A vector is an arrow with magnitude and direction.",
        "parent_id": "source:A",
        "similarity": 0.9,
    },
    {
        "title": "Other source",
        "content": "Completely unrelated passage.",
        "parent_id": "source:B",
        "similarity": 0.8,
    },
]


# --- fakes ---


class FakeLLM:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages: Any) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(
            content=self._contents.pop(0), provider="fake", model="fake"
        )


class MemStore(SessionStore):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._n = 0

    async def create(self, state: SessionState) -> str:
        self._n += 1
        sid = f"session:g{self._n}"
        self.records[sid] = {
            "id": sid,
            "user_id": state.user_id,
            "source_id": state.source_id,
            "topic": state.topic,
            "traits": state.traits.model_dump(),
            "technique": state.technique.model_dump(),
            "help": state.help.model_dump(),
            "task": state.task.model_dump(),
            "transcript": [t.model_dump() for t in state.transcript],
        }
        return sid

    async def load(self, sid: str) -> dict[str, Any]:
        try:
            return dict(self.records[sid])
        except KeyError as exc:
            raise UnknownSessionError(sid) from exc

    async def save_progress(self, state: SessionState) -> None:
        rec = self.records[state.session_id]
        rec["help"] = state.help.model_dump()
        rec["task"] = state.task.model_dump()
        rec["transcript"] = [t.model_dump() for t in state.transcript]

    async def close(self, *a: Any, **k: Any) -> None:  # pragma: no cover
        ...

    async def list(self, user_id: str, status: str | None = None) -> list[Any]:
        return []


class _Empty(BaseModel):
    pass


def _client(rows: list[dict[str, Any]] | None = None) -> OpenNotebookClient:
    rows = _ROWS if rows is None else rows

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search":
            return httpx.Response(
                200,
                json={
                    "results": rows,
                    "total_count": len(rows),
                    "search_type": "vector",
                },
            )
        if request.url.path == "/api/sources":
            return httpx.Response(
                200,
                json=[
                    {"id": "source:A", "title": "Algebra"},
                    {"id": "source:B", "title": "Other source"},
                ],
            )
        return httpx.Response(404)

    return OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )


def _registry(rows: list[dict[str, Any]] | None = None) -> ToolRegistry:
    async def read_profile(args: _Empty) -> dict[str, Any]:
        return {
            "user_id": "juanda",
            "learning_goal": "algebra",
            "self_assessed_level": "beginner",
        }

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "read", input_model=_Empty, handler=read_profile)
    )
    registry.register(content_search_tool(_client(rows)))
    return registry


def _engine(llm: FakeLLM, store: MemStore, *, grounding: bool) -> TutorEngine:
    return TutorEngine(
        llm=llm,
        registry=_registry(),
        store=store,
        user_id="juanda",
        grounding_enabled=grounding,
    )


# --- content.search source filter ---


def test_content_search_filters_by_source_via_parent_id() -> None:
    spec = content_search_tool(_client())
    registry = ToolRegistry()
    registry.register(spec)

    # bare id must match the "source:"-prefixed parent_id
    scoped = asyncio.run(
        registry.call("content.search", {"query": "vectors", "source_id": "A"})
    )
    assert scoped["total_count"] == 1
    assert scoped["results"][0]["parent_id"] == "source:A"

    unscoped = asyncio.run(registry.call("content.search", {"query": "vectors"}))
    assert unscoped["total_count"] == 2


# --- retrieve_grounding, both paths ---


def test_retrieve_grounding_ungrounded_is_legacy_digest() -> None:
    seen: dict[str, Any] = {}

    async def search(args: BaseModel) -> dict[str, Any]:
        seen["args"] = args.model_dump()
        return {"results": [{"title": "Vectors", "content": "an arrow"}]}

    class _In(BaseModel):
        query: str
        limit: int = 5

    reg = ToolRegistry()
    reg.register(ToolSpec("content.search", "s", input_model=_In, handler=search))

    result = asyncio.run(
        retrieve_grounding(reg, topic="vectores", source_id=None, enabled=True)
    )
    assert result.grounded is False
    assert result.source_id is None
    assert "Vectors" in result.content and "GROUNDED SOURCE" not in result.content
    # ungrounded call must not smuggle source_id/type — keeps legacy path intact
    assert "source_id" not in seen["args"]


def test_retrieve_grounding_grounded_formats_cited_passages() -> None:
    result = asyncio.run(
        retrieve_grounding(
            _registry(), topic="vectors", source_id="source:A", enabled=True
        )
    )
    assert result.grounded is True
    assert result.source_id == "source:A"
    assert "GROUNDED SOURCE" in result.content
    assert "[1]" in result.content
    assert "arrow with magnitude" in result.content
    assert "unrelated" not in result.content  # source:B filtered out


def test_retrieve_grounding_disabled_ignores_source() -> None:
    result = asyncio.run(
        retrieve_grounding(
            _registry(), topic="vectors", source_id="source:A", enabled=False
        )
    )
    assert result.grounded is False
    assert result.source_id is None


# --- engine integration ---


def test_engine_grounds_prompt_and_persists_anchor() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "¡Hola! Empecemos."])
    engine = _engine(llm, store, grounding=True)

    state, _ = asyncio.run(engine.open("vectores", "source:A"))

    system_prompt = llm.seen[-1][0].content
    assert (
        'GROUNDED SOURCE — "' in system_prompt
    )  # grounded-only header, not the instruction
    assert "arrow with magnitude" in system_prompt
    assert state.source_id == "source:A"
    assert store.records[state.session_id]["source_id"] == "source:A"


def test_grounded_session_survives_resume() -> None:
    store = MemStore()
    engine1 = _engine(FakeLLM([CLASSIFY, "opening"]), store, grounding=True)
    state, _ = asyncio.run(engine1.open("vectores", "source:A"))

    # fresh engine (restarted process) with no in-memory content cache
    engine2 = _engine(FakeLLM(["seguimos"]), store, grounding=True)
    _, reply = asyncio.run(engine2.message(state.session_id, "sigo aquí"))

    assert reply == "seguimos"
    resumed_prompt = engine2._llm.seen[-1][0].content  # type: ignore[attr-defined]
    # grounded-only header proves the anchor was re-derived from the store
    assert 'GROUNDED SOURCE — "' in resumed_prompt


def test_no_source_keeps_legacy_behavior_even_when_enabled() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening"])
    engine = _engine(llm, store, grounding=True)

    state, _ = asyncio.run(engine.open("vectores"))  # no source_id

    assert state.source_id is None
    assert store.records[state.session_id]["source_id"] is None
    prompt = llm.seen[-1][0].content
    assert 'GROUNDED SOURCE — "' not in prompt  # grounded-only header absent
    assert "- Algebra:" in prompt  # legacy digest bullet instead


# --- API surface ---


def test_open_response_echoes_source_id() -> None:
    store = MemStore()
    engine = _engine(FakeLLM([CLASSIFY, "opening"]), store, grounding=True)
    app = create_app(settings=TutorSettings(), engine=engine)

    body = (
        TestClient(app)
        .post("/session", json={"topic": "vectores", "source_id": "source:A"})
        .json()
    )
    assert body["source_id"] == "source:A"


def test_sources_endpoint_lists_materials() -> None:
    app = create_app(
        settings=TutorSettings(),
        client=_client(),
        engine=_engine(FakeLLM([]), MemStore(), grounding=False),
    )
    body = TestClient(app).get("/sources").json()
    assert {"id": "source:A", "title": "Algebra"} in body
    assert len(body) == 2


def test_sources_endpoint_empty_when_no_material_indexed() -> None:
    # PR-F3 polish: an empty picker is a normal state, not an error.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    app = create_app(
        settings=TutorSettings(),
        client=client,
        engine=_engine(FakeLLM([]), MemStore(), grounding=False),
    )
    response = TestClient(app).get("/sources")
    assert response.status_code == 200
    assert response.json() == []


def test_sources_endpoint_surfaces_unreachable_open_notebook_as_502() -> None:
    # PR-F3: OpenNotebook down must be a non-blocking, clearly-labeled error —
    # same convention as the other client-backed endpoints in app.py.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    app = create_app(
        settings=TutorSettings(),
        client=client,
        engine=_engine(FakeLLM([]), MemStore(), grounding=False),
    )
    response = TestClient(app).get("/sources")
    assert response.status_code == 502
    assert "ConnectError" in response.json()["detail"]


def test_ui_exposes_source_selector() -> None:
    from pathlib import Path

    html = (Path(__file__).parent.parent / "tutor" / "ui" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="source"' in html
    assert "loadSources" in html
    assert "/sources" in html
