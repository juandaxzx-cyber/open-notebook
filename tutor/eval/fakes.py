"""In-memory registry and store for eval runs (PR-E2).

The eval isolates PROMPT quality: the engine is real and the tutor LLM is
real, but profile, content and persistence are canned so no SurrealDB or
OpenNotebook instance is needed."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from tutor.eval.personas import Persona
from tutor.session.models import SessionState
from tutor.session.store import SessionStore, UnknownSessionError
from tutor.tools.registry import ToolRegistry, ToolSpec


class _SearchIn(BaseModel):
    query: str = ""
    limit: int = 5


class _EmptyIn(BaseModel):
    pass


def build_fake_registry(persona: Persona) -> ToolRegistry:
    registry = ToolRegistry()

    async def profile_read(_: _EmptyIn) -> dict[str, Any]:
        return dict(persona.profile)

    async def content_search(_: _SearchIn) -> dict[str, Any]:
        return {
            "results": [
                {"title": f"{persona.topic} — nota {i}", "content": snippet}
                for i, snippet in enumerate(persona.content, start=1)
            ]
        }

    registry.register(
        ToolSpec(
            name="profile.read",
            description="canned eval profile",
            input_model=_EmptyIn,
            handler=profile_read,
        )
    )
    registry.register(
        ToolSpec(
            name="content.search",
            description="canned eval content",
            input_model=_SearchIn,
            handler=content_search,
        )
    )
    return registry


class InMemorySessionStore(SessionStore):
    """Same contract as SessionStore, dict-backed."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._counter = 0

    async def create(self, state: SessionState) -> str:
        self._counter += 1
        session_id = f"session:eval{self._counter}"
        self._records[session_id] = {
            "id": session_id,
            "user_id": state.user_id,
            "topic": state.topic,
            "traits": state.traits.model_dump(),
            "technique": state.technique.model_dump(),
            "help": state.help.model_dump(),
            "task": state.task.model_dump(),
            "transcript": [t.model_dump() for t in state.transcript],
        }
        return session_id

    async def load(self, session_id: str) -> dict[str, Any]:
        try:
            return dict(self._records[session_id])
        except KeyError as exc:
            raise UnknownSessionError(session_id) from exc

    async def save_progress(self, state: SessionState) -> None:
        record = self._records[state.session_id]
        record["help"] = state.help.model_dump()
        record["task"] = state.task.model_dump()
        record["transcript"] = [t.model_dump() for t in state.transcript]

    async def close(
        self,
        session_id: str,
        summary: str,
        assessment: str,
        next_step: str,
        review_date: datetime,
    ) -> None:
        record = self._records[session_id]
        record["summary"] = summary
        record["assessment"] = assessment
        record["next_step"] = next_step
        record["review_date"] = review_date.isoformat()
        record["ended_at"] = datetime.now().isoformat()
