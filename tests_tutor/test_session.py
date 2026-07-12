import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tutor.app import create_app
from tutor.config import TutorSettings
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session import policy
from tutor.session.engine import TutorEngine
from tutor.session.models import ContentTraits, HelpState, SessionState
from tutor.session.store import SessionStore, UnknownSessionError
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

    async def create(self, state: SessionState) -> str:
        self._counter += 1
        session_id = f"session:test{self._counter}"
        self.records[session_id] = {
            "id": session_id,
            "user_id": state.user_id,
            "topic": state.topic,
            "traits": state.traits.model_dump(),
            "technique": state.technique.model_dump(),
            "help": state.help.model_dump(),
            "transcript": [t.model_dump() for t in state.transcript],
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
        record["transcript"] = [t.model_dump() for t in state.transcript]

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
        )


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
    assert msg.json() == {"reply": "reply", "attempts": 1, "help_level": 0}

    closed = client.post(f"/session/{session_id}/close")
    assert closed.status_code == 200
    assert closed.json()["summary"] == "covered vectors"

    fetched = client.get(f"/session/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["topic"] == "vectores"


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
