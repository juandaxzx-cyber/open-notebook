from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tutor.app import create_app
from tutor.config import TutorSettings
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session import policy
from tutor.session.engine import NoDueReviewError, TutorEngine
from tutor.session.models import ContentTraits, HelpState, SessionState
from tutor.session.store import SessionStore, UnknownSessionError, _to_naive_utc
from tutor.session.techniques import is_novice, select_technique
from tutor.tools.registry import ToolRegistry, ToolSpec

# --- fakes ---


class FakeLLM:
    """Returns queued responses in order."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(
            content=self._contents.pop(0), provider="fake", model="fake"
        )


class FakeStore(SessionStore):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self._clock = datetime(2026, 1, 1)

    def _tick(self) -> str:
        # Monotonically increasing stand-in for `updated_at` (PR-R1): each
        # write moves the fake clock forward so ordering tests are stable
        # without depending on wall-clock resolution.
        self._clock += timedelta(minutes=1)
        return self._clock.isoformat()

    async def create(self, state: SessionState) -> str:
        self._counter += 1
        session_id = f"session:test{self._counter}"
        self.records[session_id] = {
            "id": session_id,
            "user_id": state.user_id,
            "source_id": state.source_id,
            "topic": state.topic,
            "traits": state.traits.model_dump(),
            "technique": state.technique.model_dump(),
            "help": state.help.model_dump(),
            "task": state.task.model_dump(),
            "transcript": [t.model_dump() for t in state.transcript],
            "reviewed_ids": list(state.reviewed_ids),
            "review_count": 0,
            "updated_at": self._tick(),
        }
        return session_id

    async def load(self, session_id: str) -> dict[str, Any]:
        try:
            return dict(self.records[session_id])
        except KeyError as exc:
            raise UnknownSessionError(session_id) from exc

    async def save_progress(self, state: SessionState) -> None:
        record = self.records[state.session_id]
        record["help"] = state.help.model_dump()
        record["task"] = state.task.model_dump()
        record["transcript"] = [t.model_dump() for t in state.transcript]
        record["updated_at"] = self._tick()

    async def close(
        self,
        session_id: str,
        summary: str,
        assessment: str,
        next_step: str,
        review_date: datetime,
    ) -> None:
        self.records[session_id].update(
            summary=summary,
            assessment=assessment,
            next_step=next_step,
            review_date=review_date.isoformat(),
            ended_at="now",
            updated_at=self._tick(),
        )

    async def list_for_user(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [r for r in self.records.values() if r["user_id"] == user_id]
        if status == "open":
            rows = [r for r in rows if not r.get("ended_at")]
        elif status == "closed":
            rows = [r for r in rows if r.get("ended_at")]
        return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)

    async def due_items(self, user_id: str, now: datetime) -> list[dict[str, Any]]:
        cutoff = _to_naive_utc(now)
        due = [
            r
            for r in self.records.values()
            if r["user_id"] == user_id
            and r.get("ended_at")
            and r.get("review_date")
            and _to_naive_utc(r["review_date"]) <= cutoff
        ]
        due.sort(key=lambda r: _to_naive_utc(r["review_date"]))
        return due

    async def record_review(
        self, session_ids: list[str], review_date: datetime, graduate_at: int
    ) -> None:
        for sid in session_ids:
            record = self.records.get(sid)
            if not record:
                continue
            count = int(record.get("review_count") or 0) + 1
            record["review_count"] = count
            record["review_date"] = (
                None if count >= graduate_at else review_date.isoformat()
            )
            record["updated_at"] = self._tick()


class Empty(BaseModel):
    pass


class SearchArgs(BaseModel):
    query: str
    limit: int = 5


def _fake_registry() -> ToolRegistry:
    async def read_profile(args: Empty) -> dict[str, Any]:
        return {
            "user_id": "juanda",
            "learning_goal": "linear algebra",
            "self_assessed_level": "beginner",
        }

    async def search(args: SearchArgs) -> dict[str, Any]:
        return {"results": [{"title": "Vectors", "content": "A vector is..."}]}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "read", input_model=Empty, handler=read_profile)
    )
    registry.register(
        ToolSpec("content.search", "search", input_model=SearchArgs, handler=search)
    )
    return registry


CLASSIFY = '{"verifiability": "verifiable", "structure": "hierarchical", "production": "apply"}'
CLOSE = (
    '{"summary": "covered vectors", "assessment": "solid start", '
    '"next_step": "practice dot products", "review_in_days": 3}'
)


def _engine(llm: FakeLLM, store: FakeStore | None = None) -> TutorEngine:
    return TutorEngine(
        llm=llm, registry=_fake_registry(), store=store or FakeStore(), user_id="juanda"
    )


# --- techniques ---


def test_technique_mapping_apply_novice() -> None:
    traits = ContentTraits(
        verifiability="verifiable", structure="hierarchical", production="apply"
    )
    plan = select_technique(traits, "beginner, just starting")
    assert plan.primary == "faded worked examples"
    assert plan.feedback_style == "immediate corrective feedback"
    assert plan.sequencing == "prerequisites first"


def test_technique_mapping_explain_interpretive_distributed() -> None:
    traits = ContentTraits(
        verifiability="interpretive", structure="distributed", production="explain"
    )
    plan = select_technique(traits, "advanced")
    assert plan.primary == "socratic self-explanation"
    assert plan.feedback_style == "criteria-based discussion"
    assert plan.sequencing == "interleaving and connections"


def test_is_novice_spanish_and_english() -> None:
    assert is_novice("Principiante total")
    assert is_novice("beginner")
    assert not is_novice("intermediate")


# --- policy ---


def test_policy_plain_attempt_does_not_escalate() -> None:
    state = policy.next_state(HelpState(), "creo que es 42")
    assert state.attempts == 1
    assert state.help_level == 0


def test_policy_help_request_escalates_one_step() -> None:
    state = policy.next_state(HelpState(attempts=1, help_level=1), "dame una pista")
    assert state.help_level == 2


def test_policy_give_up_needs_one_attempt_first() -> None:
    first = policy.next_state(HelpState(), "me rindo")
    assert first.help_level == 1  # treated as help request, not full solution
    second = policy.next_state(first, "me rindo, dime la respuesta")
    assert second.help_level == 4


# --- engine ---


def test_engine_full_session_flow() -> None:
    store = FakeStore()
    llm = FakeLLM(
        [CLASSIFY, "¡Hola! Empecemos con vectores.", "Bien, ¿y si...?", CLOSE]
    )
    engine = _engine(llm, store)

    state, opening = asyncio.run(engine.open("vectores"))
    assert "vectores" in opening.lower() or opening
    assert state.traits.production == "apply"
    assert state.traits.source == "llm"
    assert state.technique.primary == "faded worked examples"  # beginner profile
    assert state.session_id.startswith("session:")

    state2, reply = asyncio.run(engine.message(state.session_id, "creo que es (2,3)"))
    assert reply == "Bien, ¿y si...?"
    assert state2.help.attempts == 1
    record = store.records[state.session_id]
    assert len(record["transcript"]) == 3  # opening + learner + tutor

    closed = asyncio.run(engine.close(state.session_id))
    assert closed["summary"] == "covered vectors"
    assert closed["next_step"] == "practice dot products"
    assert closed["review_date"]


def test_engine_falls_back_when_classification_is_garbage() -> None:
    llm = FakeLLM(["not json at all", "opening"])
    engine = _engine(llm)
    state, _ = asyncio.run(engine.open("philosophy"))
    assert state.traits.source == "fallback"


def test_engine_help_state_reaches_prompt() -> None:
    store = FakeStore()
    llm = FakeLLM([CLASSIFY, "opening", "here is a hint"])
    engine = _engine(llm, store)
    state, _ = asyncio.run(engine.open("vectores"))
    asyncio.run(engine.message(state.session_id, "ayuda, estoy atascado"))
    system_prompt = llm.seen[-1][0].content
    assert "maximum help allowed now: level 1" in system_prompt


# --- router ---


def test_session_endpoints_full_cycle() -> None:
    llm = FakeLLM([CLASSIFY, "opening", "reply", CLOSE])
    app = create_app(settings=TutorSettings(), engine=_engine(llm))
    client = TestClient(app)

    opened = client.post("/session", json={"topic": "vectores"})
    assert opened.status_code == 200
    body = opened.json()
    session_id = body["session_id"]
    assert body["technique"]["primary"] == "faded worked examples"

    msg = client.post(f"/session/{session_id}/message", json={"text": "intento: 42"})
    assert msg.status_code == 200
    assert msg.json() == {
        "reply": "reply",
        "attempts": 1,
        "help_level": 0,
        "task_index": 0,
        "task_label": "",
    }

    closed = client.post(f"/session/{session_id}/close")
    assert closed.status_code == 200
    assert closed.json()["summary"] == "covered vectors"

    fetched = client.get(f"/session/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["topic"] == "vectores"
    assert fetched.json()["status"] == "closed"


def test_session_unknown_id_is_404() -> None:
    llm = FakeLLM([])
    app = create_app(settings=TutorSettings(), engine=_engine(llm))
    response = TestClient(app).post("/session/session:nope/message", json={"text": "x"})
    assert response.status_code == 404


def test_session_returns_503_without_llm_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TUTOR_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TUTOR_LLM_MODEL", raising=False)
    app = create_app(settings=TutorSettings())
    response = TestClient(app).post("/session", json={"topic": "x"})
    assert response.status_code == 503


# --- dogfood regressions (F2) ---


def test_open_response_strips_marker_from_opening_message() -> None:
    # BUG 1: a task marker in the LLM opening must not reach the client;
    # the task state is derived from it instead of leaking as raw text.
    llm = FakeLLM([CLASSIFY, "[[TASK: activa tu ignorancia]]\n¿Qué sabes ya?"])
    app = create_app(settings=TutorSettings(), engine=_engine(llm))
    body = TestClient(app).post("/session", json={"topic": "svd"}).json()
    assert "[[TASK" not in body["opening_message"]
    assert body["task_index"] == 1
    assert body["task_label"] == "activa tu ignorancia"


def test_close_prompt_is_grounded_in_transcript() -> None:
    # BUG 2: the close prompt must forbid inventing learner behavior and demand
    # honesty when the session was too short to assess. Schema stays unchanged.
    from tutor.session.engine import _render

    prompt = _render(
        "close_summary.md",
        {"topic": "t", "technique_primary": "x", "transcript": "tutor: hola"},
    )
    lowered = prompt.lower()
    assert "do not invent" in lowered
    assert "too short to assess" in lowered
    assert "ground every statement" in lowered
    assert '"summary"' in prompt and '"review_in_days"' in prompt


# --- resume (PR-R1) ---


def _summary_record(
    session_id: str,
    user_id: str,
    topic: str,
    *,
    closed: bool,
    updated_at: str,
    task_index: int = 0,
    task_label: str = "",
    help_level: int = 0,
    review_date: str | None = None,
) -> dict[str, Any]:
    return {
        "id": session_id,
        "user_id": user_id,
        "topic": topic,
        "traits": {
            "verifiability": "verifiable",
            "structure": "hierarchical",
            "production": "apply",
            "source": "llm",
        },
        "technique": {"primary": "x", "feedback_style": "y", "sequencing": "z"},
        "help": {"attempts": 0, "help_level": help_level},
        "task": {"index": task_index, "label": task_label},
        "transcript": [],
        "updated_at": updated_at,
        "ended_at": "2026-01-01T00:00:00" if closed else None,
        "review_date": review_date,
    }


def test_sessions_list_scoped_ordered_and_filtered() -> None:
    store = FakeStore()
    store.records["session:a"] = _summary_record(
        "session:a",
        "juanda",
        "topic a",
        closed=False,
        updated_at="2026-01-01T10:00:00",
        task_index=1,
        task_label="warm-up",
        help_level=1,
    )
    store.records["session:b"] = _summary_record(
        "session:b",
        "juanda",
        "topic b",
        closed=True,
        updated_at="2026-01-02T10:00:00",
    )
    store.records["session:c"] = _summary_record(
        "session:c",
        "otheruser",
        "topic c",
        closed=False,
        updated_at="2026-01-03T10:00:00",
    )
    app = create_app(settings=TutorSettings(), engine=_engine(FakeLLM([]), store))
    client = TestClient(app)

    body = client.get("/sessions").json()
    # newest-updated first, scoped to the engine's user_id ("juanda") — the
    # other user's session (updated most recently of all three) is excluded.
    assert [s["session_id"] for s in body] == ["session:b", "session:a"]
    assert body[1] == {
        "session_id": "session:a",
        "topic": "topic a",
        "status": "open",
        "updated_at": "2026-01-01T10:00:00",
        "task_index": 1,
        "task_label": "warm-up",
        "help_level": 1,
        "review_date": None,
    }

    open_only = client.get("/sessions", params={"status": "open"}).json()
    assert [s["session_id"] for s in open_only] == ["session:a"]

    closed_only = client.get("/sessions", params={"status": "closed"}).json()
    assert [s["session_id"] for s in closed_only] == ["session:b"]


def test_get_session_exposes_status_and_transcript_while_open() -> None:
    store = FakeStore()
    llm = FakeLLM([CLASSIFY, "hola, empecemos"])
    engine = _engine(llm, store)
    state, _ = asyncio.run(engine.open("vectores"))

    app = create_app(settings=TutorSettings(), engine=engine)
    resp = TestClient(app).get(f"/session/{state.session_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "open"
    assert body["transcript"] == [{"role": "tutor", "content": "hola, empecemos"}]


def test_session_resumes_after_service_restart() -> None:
    """PR-R1 usable-when clause: state is fully server-derived, so a fresh
    TutorEngine (standing in for a restarted tutor process) can continue a
    session opened by a previous engine instance, as long as both share the
    same store."""
    store = FakeStore()
    engine1 = _engine(FakeLLM([CLASSIFY, "opening"]), store)
    state, _ = asyncio.run(engine1.open("vectores"))

    engine2 = _engine(FakeLLM(["still here, keep going"]), store)
    state2, reply = asyncio.run(engine2.message(state.session_id, "sigo aquí"))

    assert reply == "still here, keep going"
    assert state2.session_id == state.session_id
    assert len(store.records[state.session_id]["transcript"]) == 3  # open+learner+tutor


# --- session tracking / progress view (PR-H1) ---


def test_summary_exposes_review_date_for_closed_sessions() -> None:
    store = FakeStore()
    store.records["session:done"] = _summary_record(
        "session:done",
        "juanda",
        "vectores",
        closed=True,
        updated_at="2026-01-02T10:00:00",
        review_date="2026-01-05T00:00:00",
    )
    app = create_app(settings=TutorSettings(), engine=_engine(FakeLLM([]), store))
    body = TestClient(app).get("/sessions").json()
    assert body[0]["review_date"] == "2026-01-05T00:00:00"


def test_open_session_has_null_review_date() -> None:
    store = FakeStore()
    store.records["session:open"] = _summary_record(
        "session:open",
        "juanda",
        "abierta",
        closed=False,
        updated_at="2026-01-02T10:00:00",
    )
    app = create_app(settings=TutorSettings(), engine=_engine(FakeLLM([]), store))
    body = TestClient(app).get("/sessions").json()
    assert body[0]["review_date"] is None


def test_ui_has_history_view() -> None:
    from pathlib import Path

    html = (Path(__file__).parent.parent / "tutor" / "ui" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="history"' in html
    assert 'id="history-link"' in html
    assert "loadHistory" in html
    assert "Para repasar" in html


# --- review / cross-session memory (PR-G1) ---


def _due_record(
    sid: str,
    review_date: str | None,
    *,
    user: str = "juanda",
    topic: str = "vectores",
    review_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": sid,
        "user_id": user,
        "topic": topic,
        "ended_at": "2026-01-01T00:00:00",
        "review_date": review_date,
        "assessment": "confundió el producto punto con el cruz",
        "next_step": "practicar el producto punto",
        "summary": "cubrió vectores base",
        "review_count": review_count,
    }


def test_due_items_scoped_and_ordered() -> None:
    store = FakeStore()
    store.records["session:old"] = _due_record("session:old", "2026-01-01T00:00:00")
    store.records["session:new"] = _due_record("session:new", "2026-02-01T00:00:00")
    store.records["session:other"] = _due_record(
        "session:other", "2026-01-01T00:00:00", user="someone"
    )
    store.records["session:notdue"] = _due_record("session:notdue", None)  # evicted
    due = asyncio.run(store.due_items("juanda", datetime(2026, 6, 1)))
    # scoped to juanda, review_date present + past, most overdue first
    assert [r["id"] for r in due] == ["session:old", "session:new"]


def test_open_review_injects_prior_memory() -> None:
    store = FakeStore()
    store.records["session:x"] = _due_record("session:x", "2026-01-01T00:00:00")
    llm = FakeLLM(["¡Hola! Repasemos. ¿Qué recuerdas del producto punto?"])
    engine = _engine(llm, store)

    state, opening = asyncio.run(engine.open_review())

    assert state.reviewed_ids == ["session:x"]
    assert state.topic.startswith("Repaso:")
    prompt = llm.seen[-1][0].content
    assert "RETRIEVAL" in prompt  # the review prompt, not the normal one
    assert "producto punto" in prompt  # unfinished next step injected
    assert "confundió el producto punto" in prompt  # prior assessment injected


def test_open_review_raises_when_nothing_due() -> None:
    engine = _engine(FakeLLM([]), FakeStore())
    with pytest.raises(NoDueReviewError):
        asyncio.run(engine.open_review())


def test_review_close_reschedules_covered_items() -> None:
    store = FakeStore()
    store.records["session:x"] = _due_record("session:x", "2026-01-01T00:00:00")
    engine = _engine(FakeLLM(["opening review", CLOSE]), store)

    state, _ = asyncio.run(engine.open_review())
    asyncio.run(engine.close(state.session_id))

    item = store.records["session:x"]
    assert item["review_count"] == 1
    assert item["review_date"] is not None  # rescheduled (1 < graduation), not evicted


def test_record_review_evicts_after_graduation() -> None:
    store = FakeStore()
    store.records["session:a"] = _due_record(
        "session:a", "2026-01-01T00:00:00", review_count=2
    )
    store.records["session:b"] = _due_record(
        "session:b", "2026-01-01T00:00:00", review_count=0
    )
    future = datetime(2026, 12, 1)
    asyncio.run(store.record_review(["session:a", "session:b"], future, 3))

    assert store.records["session:a"]["review_count"] == 3
    assert store.records["session:a"]["review_date"] is None  # EVICTED at graduation
    assert store.records["session:b"]["review_count"] == 1
    assert store.records["session:b"]["review_date"] == future.isoformat()  # kept


def test_review_endpoints_list_and_open() -> None:
    store = FakeStore()
    store.records["session:x"] = _due_record("session:x", "2026-01-01T00:00:00")
    app = create_app(
        settings=TutorSettings(),
        engine=_engine(FakeLLM(["opening review"]), store),
    )
    client = TestClient(app)

    due = client.get("/reviews/due").json()
    assert due[0]["session_id"] == "session:x"
    assert due[0]["next_step"] == "practicar el producto punto"

    opened = client.post("/review")
    assert opened.status_code == 200
    assert opened.json()["opening_message"]


def test_review_open_returns_409_when_nothing_due() -> None:
    app = create_app(settings=TutorSettings(), engine=_engine(FakeLLM([]), FakeStore()))
    assert TestClient(app).post("/review").status_code == 409


def test_review_prompt_is_retrieval_first_and_interleaves() -> None:
    from tutor.session.engine import _render

    prompt = _render(
        "review_system.md",
        {
            "profile": "{}",
            "topic": "Repaso: x, y",
            "traits": "{}",
            "technique_primary": "retrieval practice",
            "technique_feedback": "contingent",
            "technique_sequencing": "interleaving prior topics",
            "content": "[1] x",
            "help_state": "level 0",
            "task_state": "none",
        },
    )
    low = prompt.lower()
    assert "retrieval" in low
    assert "interleave" in low
