"""Unit tests for tutor/usage.py (PR-BT2): daily-cap increment/enforce
seam. No network/DB — exercised directly (pure helpers) or through
`TutorEngine.message` with `tutor.eval.fakes.InMemoryUsageStore`, same
pattern as `tests_tutor/test_auth.py`."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tutor.app import create_app
from tutor.config import TutorSettings
from tutor.eval.fakes import InMemoryUsageStore
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session.engine import TutorEngine
from tutor.session.models import SessionState
from tutor.session.store import SessionStore, UnknownSessionError
from tutor.tools.registry import ToolRegistry, ToolSpec
from tutor.usage import DailyCapExceededError, today_utc

# --- today_utc / DailyCapExceededError ---


def test_today_utc_is_yyyy_mm_dd() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today_utc())


def test_daily_cap_exceeded_error_carries_context() -> None:
    exc = DailyCapExceededError("alice", "2026-07-20", 5)
    assert exc.user_id == "alice"
    assert exc.day == "2026-07-20"
    assert exc.cap == 5
    assert "5" in str(exc)
    assert "alice" in str(exc)


# --- InMemoryUsageStore (the fake used by smoke + these tests) ---


def test_in_memory_usage_store_increments_per_user_per_day() -> None:
    store = InMemoryUsageStore()
    assert asyncio.run(store.increment("alice", "2026-07-20")) == 1
    assert asyncio.run(store.increment("alice", "2026-07-20")) == 2
    assert asyncio.run(store.increment("bob", "2026-07-20")) == 1
    assert asyncio.run(store.increment("alice", "2026-07-21")) == 1


def test_in_memory_usage_store_usage_scoping() -> None:
    store = InMemoryUsageStore()
    asyncio.run(store.increment("alice", "2026-07-20"))
    asyncio.run(store.increment("bob", "2026-07-20"))
    all_rows = asyncio.run(store.usage())
    assert {r["user_id"] for r in all_rows} == {"alice", "bob"}
    alice_rows = asyncio.run(store.usage("alice"))
    assert [r["user_id"] for r in alice_rows] == ["alice"]


# --- engine.message: increment + enforce (PR-BT2 contract) ---


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        self.calls += 1
        return ChatResponse(content="ok", provider="fake", model="fake")


class Empty(BaseModel):
    pass


class SearchArgs(BaseModel):
    query: str = ""
    limit: int = 5


def _registry() -> ToolRegistry:
    async def read_profile(_: Empty) -> dict[str, Any]:
        return {
            "user_id": "juanda",
            "learning_goal": "linear algebra",
            "self_assessed_level": "beginner",
        }

    async def search(_: SearchArgs) -> dict[str, Any]:
        return {"results": []}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "read", input_model=Empty, handler=read_profile)
    )
    registry.register(
        ToolSpec("content.search", "search", input_model=SearchArgs, handler=search)
    )
    return registry


class FakeStore(SessionStore):
    """Minimal in-memory session store (create/load/save_progress only —
    all `message` needs)."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._counter = 0

    async def create(self, state: SessionState) -> str:
        self._counter += 1
        sid = f"session:test{self._counter}"
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
            "reviewed_ids": [],
        }
        return sid

    async def load(self, session_id: str) -> dict[str, Any]:
        try:
            return dict(self.records[session_id])
        except KeyError as exc:
            raise UnknownSessionError(session_id) from exc

    async def save_progress(self, state: SessionState) -> None:
        record = self.records[state.session_id]
        record["help"] = state.help.model_dump()
        record["task"] = state.task.model_dump()
        record["transcript"] = [
            t.model_dump(exclude_none=True) for t in state.transcript
        ]


def _seed_open_session(store: FakeStore, user_id: str = "juanda") -> str:
    from tutor.session.models import ContentTraits, TechniquePlan

    state = SessionState(
        session_id="",
        user_id=user_id,
        topic="vectors",
        traits=ContentTraits(
            verifiability="verifiable", structure="hierarchical", production="apply"
        ),
        technique=TechniquePlan(
            primary="faded worked examples",
            feedback_style="immediate corrective feedback",
            sequencing="prerequisites first",
        ),
    )
    return asyncio.run(store.create(state))


def test_message_below_cap_increments_and_calls_llm() -> None:
    store = FakeStore()
    sid = _seed_open_session(store)
    llm = FakeLLM()
    usage = InMemoryUsageStore()
    engine = TutorEngine(
        llm=llm,
        registry=_registry(),
        store=store,
        user_id="juanda",
        daily_turn_cap=5,
        usage_store=usage,
    )
    asyncio.run(engine.message(sid, "hola"))
    assert llm.calls == 1
    rows = asyncio.run(usage.usage("juanda"))
    assert rows[0]["turns"] == 1


def test_message_exceeding_cap_raises_before_llm_call() -> None:
    store = FakeStore()
    sid = _seed_open_session(store)
    llm = FakeLLM()
    usage = InMemoryUsageStore()
    engine = TutorEngine(
        llm=llm,
        registry=_registry(),
        store=store,
        user_id="juanda",
        daily_turn_cap=1,
        usage_store=usage,
    )
    asyncio.run(engine.message(sid, "turn 1"))
    assert llm.calls == 1
    with pytest.raises(DailyCapExceededError):
        asyncio.run(engine.message(sid, "turn 2"))
    # The LLM was never invoked for the rejected turn (enforced BEFORE the
    # LLM call, per contract) — call count stays at 1.
    assert llm.calls == 1


def test_message_zero_cap_is_unlimited_and_never_touches_usage_store() -> None:
    store = FakeStore()
    sid = _seed_open_session(store)
    llm = FakeLLM()

    class ExplodingUsageStore:
        async def increment(self, user_id: str, day: str) -> int:
            raise AssertionError("cap=0 must never touch the usage store")

        async def usage(self, user_id: str | None = None) -> list[dict[str, Any]]:
            raise AssertionError("cap=0 must never touch the usage store")

    engine = TutorEngine(
        llm=llm,
        registry=_registry(),
        store=store,
        user_id="juanda",
        daily_turn_cap=0,
        usage_store=ExplodingUsageStore(),
    )
    for _ in range(3):
        asyncio.run(engine.message(sid, "hola"))
    assert llm.calls == 3


def test_message_default_construction_cap_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct/test construction with no daily_turn_cap given at all is
    off (0) — existing tests that never mention the cap keep working
    without a usage_store, matching the grounding/memory defaults."""
    store = FakeStore()
    sid = _seed_open_session(store)
    llm = FakeLLM()
    engine = TutorEngine(llm=llm, registry=_registry(), store=store, user_id="juanda")
    asyncio.run(engine.message(sid, "hola"))
    assert llm.calls == 1


def test_message_cap_counts_per_user_per_day_scoping() -> None:
    """Two sessions for two different users share a cap value but not a
    counter — the cap is per (user_id, day), not global."""
    store = FakeStore()
    sid_alice = _seed_open_session(store, user_id="alice")
    sid_bob = _seed_open_session(store, user_id="bob")
    llm = FakeLLM()
    usage = InMemoryUsageStore()
    engine = TutorEngine(
        llm=llm,
        registry=_registry(),
        store=store,
        user_id="alice",
        daily_turn_cap=1,
        usage_store=usage,
    )
    asyncio.run(engine.message(sid_alice, "hola", user_id="alice"))
    # alice is now at her cap; bob's counter is untouched, so his turn
    # succeeds even though alice's next one would not.
    asyncio.run(engine.message(sid_bob, "hola", user_id="bob"))
    assert llm.calls == 2
    with pytest.raises(DailyCapExceededError):
        asyncio.run(engine.message(sid_alice, "de nuevo", user_id="alice"))


# --- router: DailyCapExceededError -> 429 (PR-BT2 contract) ---


def test_send_message_router_maps_daily_cap_to_429_with_friendly_message() -> None:
    store = FakeStore()
    sid = _seed_open_session(store)
    engine = TutorEngine(
        llm=FakeLLM(),
        registry=_registry(),
        store=store,
        user_id="juanda",
        daily_turn_cap=1,
        usage_store=InMemoryUsageStore(),
    )
    app = create_app(settings=TutorSettings(), engine=engine)
    client = TestClient(app)

    first = client.post(f"/session/{sid}/message", json={"text": "uno"})
    assert first.status_code == 200

    second = client.post(f"/session/{sid}/message", json={"text": "dos"})
    assert second.status_code == 429
    detail = second.json()["detail"]
    assert isinstance(detail, str) and detail  # friendly Spanish message, non-empty


def test_send_message_router_below_cap_stays_200() -> None:
    store = FakeStore()
    sid = _seed_open_session(store)
    engine = TutorEngine(
        llm=FakeLLM(),
        registry=_registry(),
        store=store,
        user_id="juanda",
        daily_turn_cap=5,
        usage_store=InMemoryUsageStore(),
    )
    app = create_app(settings=TutorSettings(), engine=engine)
    client = TestClient(app)

    for _ in range(3):
        response = client.post(f"/session/{sid}/message", json={"text": "x"})
        assert response.status_code == 200
