"""In-memory registry and store for eval runs (PR-E2) and the smoke (PR-DX2).

The eval isolates PROMPT quality: the engine is real and the tutor LLM is
real, but profile, content and persistence are canned so no SurrealDB or
OpenNotebook instance is needed. The smoke (PR-DX2) reuses the same in-memory
store and profile service to drive the full HTTP journey offline.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from tutor.eval.personas import Persona
from tutor.profile.models import Profile, ProfileIn
from tutor.profile.service import ProfileService
from tutor.session.models import SessionState
from tutor.session.store import SessionStore, UnknownSessionError, _to_naive_utc
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
    """Same contract as SessionStore, dict-backed. Mirrors every method the
    engine and router use — including list/due/review (PR-DX2) and
    consolidated memory CRUD (PR-G2) — so the whole journey runs without
    SurrealDB."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self._memories: dict[str, dict[str, Any]] = {}
        self._memory_counter = 0

    def _stamp(self) -> str:
        """Monotonic stand-in for `updated_at` so list ordering is stable."""
        self._counter += 1
        return f"{self._counter:012d}"

    async def create(self, state: SessionState) -> str:
        session_id = f"session:eval{self._counter + 1}"
        self._records[session_id] = {
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
            "updated_at": self._stamp(),
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
        record["updated_at"] = self._stamp()

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
        record["ended_at"] = datetime.now(timezone.utc).isoformat()
        record["updated_at"] = self._stamp()

    async def list_for_user(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [r for r in self._records.values() if r["user_id"] == user_id]
        if status == "open":
            rows = [r for r in rows if not r.get("ended_at")]
        elif status == "closed":
            rows = [r for r in rows if r.get("ended_at")]
        return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)

    async def due_items(self, user_id: str, now: datetime) -> list[dict[str, Any]]:
        cutoff = _to_naive_utc(now)
        due = [
            r
            for r in self._records.values()
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
            record = self._records.get(sid)
            if not record:
                continue
            count = int(record.get("review_count") or 0) + 1
            record["review_count"] = count
            record["review_date"] = (
                None if count >= graduate_at else review_date.isoformat()
            )
            record["updated_at"] = self._stamp()

    # --- consolidated learner memory (PR-G2) ---

    async def list_memories(self, user_id: str) -> list[dict[str, Any]]:
        rows = [m for m in self._memories.values() if m["user_id"] == user_id]
        return sorted(rows, key=lambda m: str(m.get("updated") or ""), reverse=True)

    async def upsert_memory(
        self,
        user_id: str,
        topic_key: str,
        topic_label: str,
        summary: str,
        mastery_estimate: float,
        recurring_errors: list[str],
        last_session_id: str | None,
    ) -> dict[str, Any]:
        existing = next(
            (
                m
                for m in self._memories.values()
                if m["user_id"] == user_id and m["topic_key"] == topic_key
            ),
            None,
        )
        self._memory_counter += 1
        if existing is not None:
            existing.update(
                topic_label=topic_label,
                summary=summary,
                mastery_estimate=mastery_estimate,
                recurring_errors=list(recurring_errors),
                sessions_count=int(existing.get("sessions_count") or 0) + 1,
                last_session_id=last_session_id,
                updated=self._stamp(),
            )
            return dict(existing)
        record_id = f"learner_memory:eval{self._memory_counter}"
        record = {
            "id": record_id,
            "user_id": user_id,
            "topic_key": topic_key,
            "topic_label": topic_label,
            "summary": summary,
            "mastery_estimate": mastery_estimate,
            "recurring_errors": list(recurring_errors),
            "sessions_count": 1,
            "last_session_id": last_session_id,
            "updated": self._stamp(),
        }
        self._memories[record_id] = record
        return dict(record)


class InMemoryProfileService(ProfileService):
    """Dict-backed ProfileService so the smoke's PUT/GET /profile and the
    engine's profile.read tool share one offline store (PR-DX2)."""

    def __init__(self) -> None:
        self._stored: dict[str, Profile] = {}

    async def get_profile(self, user_id: str) -> Profile | None:
        return self._stored.get(user_id)

    async def upsert_profile(self, user_id: str, payload: ProfileIn) -> Profile:
        profile = Profile(user_id=user_id, **payload.model_dump())
        self._stored[user_id] = profile
        return profile
