"""In-memory registry and store for eval runs (PR-E2) and the smoke (PR-DX2).

The eval isolates PROMPT quality: the engine is real and the tutor LLM is
real, but profile, content and persistence are canned so no SurrealDB or
OpenNotebook instance is needed. The smoke (PR-DX2) reuses the same in-memory
store and profile service to drive the full HTTP journey offline.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from tutor.eval.personas import Persona
from tutor.ownership import normalize_source_id
from tutor.profile.models import Profile, ProfileIn
from tutor.profile.service import ProfileService
from tutor.session.models import SessionState
from tutor.session.scheduling import sm2_next
from tutor.session.store import (
    SessionStore,
    UnknownSessionError,
    _seed_interval_days,
    _to_naive_utc,
)
from tutor.tools.registry import ToolRegistry, ToolSpec


class _SearchIn(BaseModel):
    query: str = ""
    limit: int = 5


class _EmptyIn(BaseModel):
    pass


class _GetSourceIn(BaseModel):
    source_id: str


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
    # W1-eval addendum: only registered when the persona carries a
    # `source_id` — this is what the whole-source-lite path
    # (`tutor.session.grounding._try_whole_source`) calls. Sourceless
    # personas never hit this tool, so their runs stay byte-identical.
    if persona.source_id:

        async def content_get_source(_input: _GetSourceIn) -> dict[str, Any]:
            return {"full_text": persona.source_text, "title": persona.name}

        registry.register(
            ToolSpec(
                name="content.get_source",
                description="canned eval whole-source text",
                input_model=_GetSourceIn,
                handler=content_get_source,
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
            "transcript": [t.model_dump(exclude_none=True) for t in state.transcript],
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
        record["transcript"] = [
            t.model_dump(exclude_none=True) for t in state.transcript
        ]
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
        self,
        session_ids: list[str],
        grades: dict[str, float],
        now: datetime,
        horizon_days: float,
    ) -> None:
        """Mirrors `tutor.session.store.SessionStore.record_review` (PR-G3):
        per-item SM-2 update, evict-by-horizon instead of count."""
        for sid in session_ids:
            record = self._records.get(sid)
            if not record:
                continue
            ease = record.get("ease")
            ease = 2.5 if ease is None else float(ease)
            interval = record.get("review_interval_days")
            interval = (
                _seed_interval_days(record) if interval is None else float(interval)
            )
            quality = grades.get(sid, 3.0)
            new_ease, new_interval, evict = sm2_next(
                ease, interval, quality, horizon_days
            )
            record["ease"] = new_ease
            record["review_interval_days"] = new_interval
            record["review_count"] = int(record.get("review_count") or 0) + 1
            record["review_date"] = (
                None if evict else (now + timedelta(days=new_interval)).isoformat()
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


class InMemoryUsageStore:
    """Same contract as `tutor.usage.UsageCounterStore`, dict-backed
    (PR-BT2). Mirrors `InMemorySessionStore`'s role: lets the smoke journey
    exercise the daily-cap increment/enforce path end-to-end without
    SurrealDB, cap wired on (not disabled) so it "passes naturally" per the
    PR-BT2 contract rather than being bypassed."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}

    async def increment(self, user_id: str, day: str) -> int:
        key = (user_id, day)
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def usage(self, user_id: str | None = None) -> list[dict[str, Any]]:
        rows = [
            {"user_id": u, "day": d, "turns": n}
            for (u, d), n in self._counts.items()
            if user_id is None or u == user_id
        ]
        return sorted(
            rows, key=lambda r: (str(r["user_id"]), str(r["day"])), reverse=True
        )


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


class InMemorySourceOwnerStore:
    """Same contract as `tutor.ownership.SourceOwnerStore`, dict-backed
    (PR-BT3). Grandfather clause: a source_id with no row is public — the
    same rule the real store enforces. Used by `tests_tutor/test_ownership.py`
    and the smoke's upload step."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    async def create(self, source_id: str, user_id: str, public: bool = False) -> None:
        key = normalize_source_id(source_id)
        self._rows[key] = {"source_id": key, "user_id": user_id, "public": public}

    async def get(self, source_id: str) -> dict[str, Any] | None:
        key = normalize_source_id(source_id)
        row = self._rows.get(key)
        return dict(row) if row else None

    async def is_visible(self, source_id: str, user_id: str) -> bool:
        row = await self.get(source_id)
        if row is None:
            return True
        if bool(row.get("public")):
            return True
        return str(row.get("user_id")) == user_id

    async def share(self, source_id: str) -> bool:
        key = normalize_source_id(source_id)
        row = self._rows.get(key)
        if row is None or bool(row.get("public")):
            return False
        row["public"] = True
        return True

    async def list_all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows.values()]
