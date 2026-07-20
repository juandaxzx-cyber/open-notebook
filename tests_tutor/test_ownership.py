"""PR-BT3 — private sources (tutor-side ownership; ZERO OpenNotebook core
changes). Covers: `tutor/ownership.py` CRUD + grandfather clause + share
(via `InMemorySourceOwnerStore`, same fake/protocol split as
`tests_tutor/test_auth.py` / `test_usage.py`); the `retrieve_grounding`
visibility gate (grounded short-circuit + ungrounded digest filter); engine
integration (cross-user grounding blocked, own/grandfathered/public allowed,
resume re-derives the gate); the `/sources` picker filter + "privado" flag;
and the `/sources/upload` + `/sources/create` proxy endpoints. No network/DB
in any test."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tutor.app import create_app
from tutor.auth import hash_token
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.eval.fakes import InMemorySourceOwnerStore
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.ownership import normalize_source_id
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


# --- normalize_source_id ---


def test_normalize_source_id_strips_prefix() -> None:
    assert normalize_source_id("source:abc123") == "abc123"


def test_normalize_source_id_passthrough_bare() -> None:
    assert normalize_source_id("abc123") == "abc123"


def test_normalize_source_id_handles_none() -> None:
    assert normalize_source_id(None) == ""


# --- InMemorySourceOwnerStore: grandfather clause, CRUD, share ---


def test_grandfathered_source_is_visible_to_everyone() -> None:
    store = InMemorySourceOwnerStore()
    assert asyncio.run(store.is_visible("source:legacy", "alice")) is True
    assert asyncio.run(store.is_visible("source:legacy", "bob")) is True


def test_private_source_visible_only_to_owner() -> None:
    store = InMemorySourceOwnerStore()
    asyncio.run(store.create("source:mine", "alice"))
    assert asyncio.run(store.is_visible("source:mine", "alice")) is True
    assert asyncio.run(store.is_visible("source:mine", "bob")) is False


def test_public_source_visible_to_everyone() -> None:
    store = InMemorySourceOwnerStore()
    asyncio.run(store.create("source:mine", "alice", public=True))
    assert asyncio.run(store.is_visible("source:mine", "bob")) is True


def test_create_normalizes_prefixed_and_bare_ids_the_same() -> None:
    store = InMemorySourceOwnerStore()
    asyncio.run(store.create("source:mine", "alice"))
    assert asyncio.run(store.get("mine")) is not None
    row = asyncio.run(store.get("source:mine"))
    assert row is not None and row["source_id"] == "mine"


def test_share_flips_public_and_is_idempotent() -> None:
    store = InMemorySourceOwnerStore()
    asyncio.run(store.create("source:mine", "alice"))
    assert asyncio.run(store.is_visible("source:mine", "bob")) is False

    changed = asyncio.run(store.share("source:mine"))
    assert changed is True
    assert asyncio.run(store.is_visible("source:mine", "bob")) is True

    changed_again = asyncio.run(store.share("source:mine"))
    assert changed_again is False  # already public -> no-op


def test_share_on_grandfathered_source_is_a_noop() -> None:
    store = InMemorySourceOwnerStore()
    changed = asyncio.run(store.share("source:never-uploaded"))
    assert changed is False


def test_list_all_returns_every_row() -> None:
    store = InMemorySourceOwnerStore()
    asyncio.run(store.create("source:a", "alice"))
    asyncio.run(store.create("source:b", "bob", public=True))
    rows = asyncio.run(store.list_all())
    assert {r["source_id"] for r in rows} == {"a", "b"}


# --- retrieve_grounding: the visibility gate ---


class _SearchIn(BaseModel):
    query: str
    limit: int = 10
    type: str = "text"
    source_id: str | None = None


class _GetSourceIn(BaseModel):
    source_id: str


def _exploding_registry() -> ToolRegistry:
    """A search/get_source tool that raises if ever called — proves the
    grounded path never touches OpenNotebook for a source the requester
    cannot see. This matters: unlike a genuinely nonexistent source_id
    (whose search legitimately returns nothing), calling the real search
    API with a private-but-EXISTING one WOULD return real matches, since
    OpenNotebook itself has no per-user scoping."""

    async def boom_search(_: _SearchIn) -> dict[str, Any]:
        raise AssertionError(
            "content.search must not be called for an invisible source"
        )

    async def boom_get_source(_: _GetSourceIn) -> dict[str, Any]:
        raise AssertionError(
            "content.get_source must not be called for an invisible source"
        )

    registry = ToolRegistry()
    registry.register(
        ToolSpec("content.search", "s", input_model=_SearchIn, handler=boom_search)
    )
    registry.register(
        ToolSpec(
            "content.get_source", "g", input_model=_GetSourceIn, handler=boom_get_source
        )
    )
    return registry


def test_retrieve_grounding_invisible_source_never_calls_opennotebook() -> None:
    async def cannot_view(_source_id: str) -> bool:
        return False

    result = asyncio.run(
        retrieve_grounding(
            _exploding_registry(),
            topic="algebra",
            source_id="source:private1",
            enabled=True,
            can_view=cannot_view,
        )
    )
    assert result.grounded is True
    assert result.source_id == "source:private1"
    assert "no passages matched" in result.content


def test_retrieve_grounding_invisible_source_matches_unknown_source_message() -> None:
    """The invisible-source short-circuit must render byte-identically to
    what an actually-nonexistent source_id already produces (empty rows
    through the real search path) — "treat as nonexistent" (contract)."""

    async def empty_search(_: _SearchIn) -> dict[str, Any]:
        return {"results": []}

    registry_unknown = ToolRegistry()
    registry_unknown.register(
        ToolSpec("content.search", "s", input_model=_SearchIn, handler=empty_search)
    )

    async def deny(_: str) -> bool:
        return False

    unknown_result = asyncio.run(
        retrieve_grounding(
            registry_unknown, topic="x", source_id="source:ghost", enabled=True
        )
    )
    invisible_result = asyncio.run(
        retrieve_grounding(
            _exploding_registry(),
            topic="x",
            source_id="source:ghost",
            enabled=True,
            can_view=deny,
        )
    )
    assert unknown_result.content == invisible_result.content
    assert unknown_result.grounded is True and invisible_result.grounded is True


def test_retrieve_grounding_visible_source_still_retrieves() -> None:
    async def can_view(_source_id: str) -> bool:
        return True

    async def search(_: _SearchIn) -> dict[str, Any]:
        return {
            "results": [
                {
                    "title": "Algebra",
                    "content": "vectors are arrows",
                    "parent_id": "source:A",
                }
            ]
        }

    registry = ToolRegistry()
    registry.register(
        ToolSpec("content.search", "s", input_model=_SearchIn, handler=search)
    )

    result = asyncio.run(
        retrieve_grounding(
            registry,
            topic="vectors",
            source_id="source:A",
            enabled=True,
            can_view=can_view,
        )
    )
    assert result.grounded is True
    assert "vectors are arrows" in result.content


def test_retrieve_grounding_can_view_omitted_is_backward_compatible() -> None:
    # Additive keyword-only param — omitting it entirely keeps the grounded
    # path byte-identical to pre-BT3 (M1-style lock).
    async def search(_: _SearchIn) -> dict[str, Any]:
        return {
            "results": [
                {"title": "X", "content": "unchecked", "parent_id": "source:whatever"}
            ]
        }

    registry = ToolRegistry()
    registry.register(
        ToolSpec("content.search", "s", input_model=_SearchIn, handler=search)
    )
    result = asyncio.run(
        retrieve_grounding(
            registry, topic="x", source_id="source:whatever", enabled=True
        )
    )
    assert "unchecked" in result.content


# --- retrieve_grounding: ungrounded digest filter ---


def test_ungrounded_digest_filters_out_invisible_source_rows() -> None:
    rows = [
        {"title": "Mine", "content": "public stuff", "parent_id": "source:public1"},
        {"title": "Theirs", "content": "secret stuff", "parent_id": "source:private1"},
        {"title": "A note", "content": "note content", "parent_id": "note:xyz"},
    ]

    async def search(_: _SearchIn) -> dict[str, Any]:
        return {"results": rows}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("content.search", "s", input_model=_SearchIn, handler=search)
    )

    async def can_view(source_id: str) -> bool:
        return normalize_source_id(source_id) != "private1"

    result = asyncio.run(
        retrieve_grounding(
            registry, topic="algebra", source_id=None, enabled=True, can_view=can_view
        )
    )
    assert result.grounded is False
    assert "public stuff" in result.content
    assert "note content" in result.content  # notes aren't source-owned
    assert "secret stuff" not in result.content


def test_ungrounded_digest_unfiltered_when_can_view_absent() -> None:
    # Backward-compat lock (BT1/M1-style): omitting can_view keeps the
    # legacy digest byte-identical — no ownership store ever touched.
    rows = [
        {"title": "Theirs", "content": "secret stuff", "parent_id": "source:private1"}
    ]

    async def search(_: _SearchIn) -> dict[str, Any]:
        return {"results": rows}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("content.search", "s", input_model=_SearchIn, handler=search)
    )

    result = asyncio.run(
        retrieve_grounding(registry, topic="algebra", source_id=None, enabled=True)
    )
    assert "secret stuff" in result.content


# --- engine integration ---


class _FakeLLM:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages: Any) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(
            content=self._contents.pop(0), provider="fake", model="fake"
        )


class _MemStore(SessionStore):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._n = 0

    async def create(self, state: SessionState) -> str:
        self._n += 1
        sid = f"session:o{self._n}"
        self.records[sid] = {
            "id": sid,
            "user_id": state.user_id,
            "source_id": state.source_id,
            "topic": state.topic,
            "traits": state.traits.model_dump(),
            "technique": state.technique.model_dump(),
            "help": state.help.model_dump(),
            "task": state.task.model_dump(),
            "transcript": [t.model_dump(exclude_none=True) for t in state.transcript],
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
        rec["transcript"] = [t.model_dump(exclude_none=True) for t in state.transcript]


class _Empty(BaseModel):
    pass


def _registry_with_rows(rows: list[dict[str, Any]]) -> ToolRegistry:
    async def read_profile(_: _Empty) -> dict[str, Any]:
        return {
            "user_id": "x",
            "learning_goal": "algebra",
            "self_assessed_level": "beginner",
        }

    async def search(_: _SearchIn) -> dict[str, Any]:
        return {"results": rows}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "read", input_model=_Empty, handler=read_profile)
    )
    registry.register(
        ToolSpec("content.search", "search", input_model=_SearchIn, handler=search)
    )
    return registry


def test_engine_blocks_grounding_on_a_source_the_requester_does_not_own() -> None:
    owner_store = InMemorySourceOwnerStore()
    asyncio.run(owner_store.create("source:alice-private", "alice"))
    rows = [
        {
            "title": "Alice's notes",
            "content": "secret formula",
            "parent_id": "source:alice-private",
        }
    ]
    store = _MemStore()
    llm = _FakeLLM([CLASSIFY, "hola bob"])
    engine = TutorEngine(
        llm=llm,
        registry=_registry_with_rows(rows),
        store=store,
        user_id="bob",
        grounding_enabled=True,
        ownership_store=owner_store,
    )
    state, _ = asyncio.run(
        engine.open("algebra", "source:alice-private", user_id="bob")
    )
    system_prompt = llm.seen[-1][0].content
    assert "secret formula" not in system_prompt
    assert state.source_id == "source:alice-private"  # anchor kept, content empty


def test_engine_allows_grounding_on_own_private_source() -> None:
    owner_store = InMemorySourceOwnerStore()
    asyncio.run(owner_store.create("source:alice-private", "alice"))
    rows = [
        {
            "title": "Alice's notes",
            "content": "secret formula",
            "parent_id": "source:alice-private",
        }
    ]
    store = _MemStore()
    llm = _FakeLLM([CLASSIFY, "hola alice"])
    engine = TutorEngine(
        llm=llm,
        registry=_registry_with_rows(rows),
        store=store,
        user_id="alice",
        grounding_enabled=True,
        ownership_store=owner_store,
    )
    asyncio.run(engine.open("algebra", "source:alice-private", user_id="alice"))
    system_prompt = llm.seen[-1][0].content
    assert "secret formula" in system_prompt


def test_engine_allows_grounding_on_grandfathered_source_for_anyone() -> None:
    owner_store = InMemorySourceOwnerStore()  # no rows at all
    rows = [
        {
            "title": "Legacy",
            "content": "curated corpus text",
            "parent_id": "source:legacy",
        }
    ]
    store = _MemStore()
    llm = _FakeLLM([CLASSIFY, "hola"])
    engine = TutorEngine(
        llm=llm,
        registry=_registry_with_rows(rows),
        store=store,
        user_id="anyone",
        grounding_enabled=True,
        ownership_store=owner_store,
    )
    asyncio.run(engine.open("algebra", "source:legacy", user_id="anyone"))
    system_prompt = llm.seen[-1][0].content
    assert "curated corpus text" in system_prompt


def test_engine_allows_grounding_on_shared_source_for_non_owner() -> None:
    owner_store = InMemorySourceOwnerStore()
    asyncio.run(owner_store.create("source:shared", "alice", public=True))
    rows = [{"title": "Shared", "content": "shared text", "parent_id": "source:shared"}]
    store = _MemStore()
    llm = _FakeLLM([CLASSIFY, "hola bob"])
    engine = TutorEngine(
        llm=llm,
        registry=_registry_with_rows(rows),
        store=store,
        user_id="bob",
        grounding_enabled=True,
        ownership_store=owner_store,
    )
    asyncio.run(engine.open("algebra", "source:shared", user_id="bob"))
    system_prompt = llm.seen[-1][0].content
    assert "shared text" in system_prompt


def test_engine_without_ownership_store_is_backward_compatible() -> None:
    # Additive constructor param: omitting it entirely (every pre-BT3 test)
    # never touches an ownership store and behaves exactly as before — no
    # visibility filtering at all.
    rows = [
        {
            "title": "Whatever",
            "content": "unchecked content",
            "parent_id": "source:whatever",
        }
    ]
    store = _MemStore()
    llm = _FakeLLM([CLASSIFY, "hola"])
    engine = TutorEngine(
        llm=llm,
        registry=_registry_with_rows(rows),
        store=store,
        user_id="anyone",
        grounding_enabled=True,
    )
    asyncio.run(engine.open("algebra", "source:whatever", user_id="anyone"))
    system_prompt = llm.seen[-1][0].content
    assert "unchecked content" in system_prompt


def test_message_resume_path_regrounds_via_ownership_gate() -> None:
    """A fresh engine instance (simulated restart, no in-memory content
    cache) must re-derive grounding through the SAME can_view gate `open`
    uses — proven here by resuming alice's own private session and still
    seeing her content."""
    owner_store = InMemorySourceOwnerStore()
    asyncio.run(owner_store.create("source:mine", "alice"))
    rows = [
        {
            "title": "Mine",
            "content": "resumed private content",
            "parent_id": "source:mine",
        }
    ]
    store = _MemStore()
    engine1 = TutorEngine(
        llm=_FakeLLM([CLASSIFY, "hola"]),
        registry=_registry_with_rows(rows),
        store=store,
        user_id="alice",
        grounding_enabled=True,
        ownership_store=owner_store,
    )
    state, _ = asyncio.run(engine1.open("algebra", "source:mine", user_id="alice"))

    llm2 = _FakeLLM(["sigo"])
    engine2 = TutorEngine(
        llm=llm2,
        registry=_registry_with_rows(rows),
        store=store,
        user_id="alice",
        grounding_enabled=True,
        ownership_store=owner_store,
    )
    _, reply = asyncio.run(
        engine2.message(state.session_id, "sigo aquí", user_id="alice")
    )
    assert reply == "sigo"
    resumed_prompt = llm2.seen[-1][0].content
    assert "resumed private content" in resumed_prompt


# --- /sources picker: own + public only, "privado" flag ---


def _picker_sources_client() -> OpenNotebookClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sources":
            return httpx.Response(
                200,
                json=[
                    {"id": "source:legacy", "title": "Legacy corpus"},
                    {"id": "source:alice-private", "title": "Alice's upload"},
                    {"id": "source:alice-shared", "title": "Alice's shared upload"},
                    {"id": "source:bob-private", "title": "Bob's upload"},
                ],
            )
        return httpx.Response(404)

    return OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )


class _FakeAccessTokenStore:
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self._rows = rows

    async def get_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self._rows.get(token_hash)


def _empty_profile_engine() -> TutorEngine:
    async def read_profile(_: _Empty) -> dict[str, Any]:
        return {}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "r", input_model=_Empty, handler=read_profile)
    )
    return TutorEngine(
        llm=_FakeLLM([]), registry=registry, store=_MemStore(), user_id="alice"
    )


def test_sources_picker_filters_own_public_and_flags_private_badge() -> None:
    owner_store = InMemorySourceOwnerStore()
    asyncio.run(owner_store.create("source:alice-private", "alice"))
    asyncio.run(owner_store.create("source:alice-shared", "alice", public=True))
    asyncio.run(owner_store.create("source:bob-private", "bob"))

    token_store = _FakeAccessTokenStore(
        {
            hash_token("alice-token"): {"user_id": "alice", "revoked": False},
            hash_token("bob-token"): {"user_id": "bob", "revoked": False},
        }
    )

    app = create_app(
        settings=TutorSettings(auth_enabled=True),
        client=_picker_sources_client(),
        engine=_empty_profile_engine(),
        auth_store=token_store,
        ownership_store=owner_store,
    )
    client = TestClient(app)

    alice_body = client.get(
        "/sources", headers={"Authorization": "Bearer alice-token"}
    ).json()
    alice_ids = {s["id"] for s in alice_body}
    assert alice_ids == {"source:legacy", "source:alice-private", "source:alice-shared"}
    by_id = {s["id"]: s for s in alice_body}
    assert by_id["source:alice-private"]["private"] is True
    assert by_id["source:alice-shared"]["private"] is False  # shared -> no badge
    assert by_id["source:legacy"]["private"] is False  # grandfathered

    bob_body = client.get(
        "/sources", headers={"Authorization": "Bearer bob-token"}
    ).json()
    bob_ids = {s["id"] for s in bob_body}
    assert bob_ids == {"source:legacy", "source:alice-shared", "source:bob-private"}
    assert "source:alice-private" not in bob_ids


def test_sources_picker_empty_ownership_store_is_all_public() -> None:
    app = create_app(
        settings=TutorSettings(),
        client=_picker_sources_client(),
        engine=_empty_profile_engine(),
        ownership_store=InMemorySourceOwnerStore(),
    )
    body = TestClient(app).get("/sources").json()
    assert len(body) == 4
    assert all(item["private"] is False for item in body)


# --- upload / create proxy endpoints ---


class _FakeUploadClient(OpenNotebookClient):
    def __init__(self) -> None:
        super().__init__(base_url="http://on:5055")
        self.upload_calls: list[tuple[str, bytes, str | None]] = []
        self.json_calls: list[dict[str, Any]] = []

    async def create_source_from_file(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        *,
        title: str | None = None,
    ) -> dict[str, Any]:
        self.upload_calls.append((filename, content, content_type))
        return {"id": "source:uploaded1", "title": title or filename}

    async def create_source_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.json_calls.append(payload)
        return {"id": "source:uploaded2", "title": payload.get("title") or "created"}


def _upload_engine() -> TutorEngine:
    async def read_profile(_: _Empty) -> dict[str, Any]:
        return {}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "r", input_model=_Empty, handler=read_profile)
    )
    return TutorEngine(
        llm=_FakeLLM([]), registry=registry, store=_MemStore(), user_id="juanda"
    )


def test_upload_endpoint_proxies_and_writes_private_ownership() -> None:
    client_stub = _FakeUploadClient()
    owner_store = InMemorySourceOwnerStore()
    app = create_app(
        settings=TutorSettings(),
        client=client_stub,
        engine=_upload_engine(),
        ownership_store=owner_store,
    )
    response = TestClient(app).post(
        "/sources/upload",
        files={"file": ("notes.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"title": "My notes"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "source:uploaded1"
    assert body["private"] is True
    assert client_stub.upload_calls[0][0] == "notes.pdf"
    row = asyncio.run(owner_store.get("source:uploaded1"))
    assert row is not None
    assert row["user_id"] == "juanda"
    assert row["public"] is False


def test_create_endpoint_url_proxies_and_writes_private_ownership() -> None:
    client_stub = _FakeUploadClient()
    owner_store = InMemorySourceOwnerStore()
    app = create_app(
        settings=TutorSettings(),
        client=client_stub,
        engine=_upload_engine(),
        ownership_store=owner_store,
    )
    response = TestClient(app).post(
        "/sources/create", json={"url": "https://example.com/article"}
    )
    assert response.status_code == 200
    assert client_stub.json_calls[0]["url"] == "https://example.com/article"
    assert client_stub.json_calls[0]["type"] == "link"
    assert client_stub.json_calls[0]["async_processing"] is True
    row = asyncio.run(owner_store.get("source:uploaded2"))
    assert row is not None and row["public"] is False


def test_create_endpoint_text_proxies() -> None:
    client_stub = _FakeUploadClient()
    owner_store = InMemorySourceOwnerStore()
    app = create_app(
        settings=TutorSettings(),
        client=client_stub,
        engine=_upload_engine(),
        ownership_store=owner_store,
    )
    response = TestClient(app).post(
        "/sources/create", json={"text": "some raw text", "title": "Nota"}
    )
    assert response.status_code == 200
    assert client_stub.json_calls[0]["content"] == "some raw text"
    assert client_stub.json_calls[0]["type"] == "text"
    assert client_stub.json_calls[0]["title"] == "Nota"


def test_create_endpoint_rejects_both_url_and_text() -> None:
    app = create_app(
        settings=TutorSettings(), client=_FakeUploadClient(), engine=_upload_engine()
    )
    response = TestClient(app).post(
        "/sources/create", json={"url": "https://x", "text": "y"}
    )
    assert response.status_code == 422


def test_create_endpoint_rejects_neither_url_nor_text() -> None:
    app = create_app(
        settings=TutorSettings(), client=_FakeUploadClient(), engine=_upload_engine()
    )
    response = TestClient(app).post("/sources/create", json={})
    assert response.status_code == 422


def test_upload_endpoint_surfaces_502_when_ownership_write_fails() -> None:
    class _ExplodingOwnershipStore:
        async def create(
            self, source_id: str, user_id: str, public: bool = False
        ) -> None:
            raise RuntimeError("db down")

        async def get(self, source_id: str) -> dict[str, Any] | None:
            return None

        async def is_visible(self, source_id: str, user_id: str) -> bool:
            return True

        async def share(self, source_id: str) -> bool:
            return False

        async def list_all(self) -> list[dict[str, Any]]:
            return []

    client_stub = _FakeUploadClient()
    app = create_app(
        settings=TutorSettings(),
        client=client_stub,
        engine=_upload_engine(),
        ownership_store=_ExplodingOwnershipStore(),
    )
    response = TestClient(app).post(
        "/sources/upload", files={"file": ("x.txt", b"hi", "text/plain")}
    )
    assert response.status_code == 502


# --- end-to-end HTTP: someone else's private source never leaks content ---


def test_http_session_open_on_others_private_source_gets_no_content() -> None:
    owner_store = InMemorySourceOwnerStore()
    asyncio.run(owner_store.create("source:alice-private", "alice"))
    rows = [
        {
            "title": "Alice's notes",
            "content": "TOP SECRET FORMULA",
            "parent_id": "source:alice-private",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search":
            return httpx.Response(
                200,
                json={"results": rows, "total_count": 1, "search_type": "vector"},
            )
        return httpx.Response(404)

    on_client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )

    async def read_profile(_: _Empty) -> dict[str, Any]:
        return {
            "user_id": "bob",
            "learning_goal": "algebra",
            "self_assessed_level": "beginner",
        }

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "r", input_model=_Empty, handler=read_profile)
    )
    registry.register(content_search_tool(on_client))

    llm = _FakeLLM([CLASSIFY, "hola bob"])
    engine = TutorEngine(
        llm=llm,
        registry=registry,
        store=_MemStore(),
        user_id="bob",
        grounding_enabled=True,
        ownership_store=owner_store,
    )
    app = create_app(settings=TutorSettings(), client=on_client, engine=engine)
    response = TestClient(app).post(
        "/session", json={"topic": "algebra", "source_id": "source:alice-private"}
    )
    assert response.status_code == 200
    seen_text = "".join(m.content for call in llm.seen for m in call)
    assert "TOP SECRET FORMULA" not in seen_text
