"""Per-task state and reset in the engine (PR-E2 part a)."""

import asyncio
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session.engine import TutorEngine
from tutor.session.models import SessionState
from tutor.session.store import SessionStore, UnknownSessionError
from tutor.tools.registry import ToolRegistry, ToolSpec

CLASSIFY = (
    '{"verifiability": "verifiable", "structure": "hierarchical", '
    '"production": "apply"}'
)


class FakeLLM:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(content=self._contents.pop(0), provider="f", model="f")


class FakeStore(SessionStore):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._n = 0

    async def create(self, state: SessionState) -> str:
        self._n += 1
        sid = f"session:t{self._n}"
        self.records[sid] = {
            "id": sid,
            "user_id": state.user_id,
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
        r = self.records[state.session_id]
        r["help"] = state.help.model_dump()
        r["task"] = state.task.model_dump()
        r["transcript"] = [t.model_dump() for t in state.transcript]

    async def close(self, *a: Any, **k: Any) -> None:  # unused here
        raise NotImplementedError


class Empty(BaseModel):
    pass


class SearchArgs(BaseModel):
    query: str
    limit: int = 5


def _registry() -> ToolRegistry:
    async def read_profile(_: Empty) -> dict[str, Any]:
        return {"self_assessed_level": "beginner"}

    async def search(_: SearchArgs) -> dict[str, Any]:
        return {"results": [{"title": "x", "content": "y"}]}

    reg = ToolRegistry()
    reg.register(ToolSpec("profile.read", "r", input_model=Empty, handler=read_profile))
    reg.register(
        ToolSpec("content.search", "s", input_model=SearchArgs, handler=search)
    )
    return reg


def _engine(llm: FakeLLM, store: FakeStore) -> TutorEngine:
    return TutorEngine(llm=llm, registry=_registry(), store=store, user_id="u")


def test_opening_marker_moves_to_task_one_and_strips_it() -> None:
    store = FakeStore()
    llm = FakeLLM([CLASSIFY, "[[TASK: sumar vectores]]\nSuma (1,2)+(3,4)."])
    engine = _engine(llm, store)
    state, opening = asyncio.run(engine.open("vectores"))
    assert state.task.index == 1
    assert state.task.label == "sumar vectores"
    assert "[[TASK" not in opening
    # raw reply (with marker) is what gets stored in the transcript
    assert "[[TASK" in store.records[state.session_id]["transcript"][0]["content"]


def test_new_task_resets_attempts_and_help() -> None:
    store = FakeStore()
    llm = FakeLLM(
        [
            CLASSIFY,
            "[[TASK: tarea 1]] primera tarea",
            "una pista",  # same task, learner asked for help
            "[[TASK: tarea 2]] segunda tarea",  # new task -> reset
        ]
    )
    engine = _engine(llm, store)
    state, _ = asyncio.run(engine.open("t"))
    state, _ = asyncio.run(engine.message(state.session_id, "ayuda, no sé"))
    assert state.help.attempts == 1 and state.help.help_level == 1
    assert state.task.index == 1
    state, _ = asyncio.run(engine.message(state.session_id, "vale, ¿ahora qué?"))
    assert state.task.index == 2 and state.task.label == "tarea 2"
    assert state.help.attempts == 0 and state.help.help_level == 0


def test_no_marker_keeps_implicit_task_zero() -> None:
    store = FakeStore()
    llm = FakeLLM([CLASSIFY, "Hola, empecemos.", "sigue así"])
    engine = _engine(llm, store)
    state, _ = asyncio.run(engine.open("t"))
    assert state.task.index == 0
    state, _ = asyncio.run(engine.message(state.session_id, "intento"))
    assert state.task.index == 0
    assert state.help.attempts == 1  # help ladder still advances within task 0


def test_task_state_injected_into_prompt() -> None:
    store = FakeStore()
    llm = FakeLLM([CLASSIFY, "[[TASK: mi tarea]] haz esto", "ok"])
    engine = _engine(llm, store)
    state, _ = asyncio.run(engine.open("t"))
    asyncio.run(engine.message(state.session_id, "hecho"))
    system_prompt = llm.seen[-1][0].content
    assert 'current task: #1 — "mi tarea"' in system_prompt
