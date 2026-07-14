"""Session persistence over the atenea database."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tutor.db import atenea_db, ensure_ok
from tutor.session.models import SessionState


class UnknownSessionError(KeyError):
    pass


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        if result and isinstance(result[0], list):
            return [r for r in result[0] if isinstance(r, dict)]
        return [r for r in result if isinstance(r, dict)]
    return []


def _to_naive_utc(value: Any) -> datetime:
    """Best-effort parse of a stored review_date (SurrealDB datetime or ISO
    string) into a naive-UTC datetime for comparison (PR-G1)."""
    dt = value if isinstance(value, datetime) else None
    if dt is None:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return datetime.max
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class SessionStore:
    async def create(self, state: SessionState) -> str:
        """Persist a new session; returns the record id."""
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    """
                    CREATE session CONTENT {
                        user_id: $user_id,
                        topic: $topic,
                        traits: $traits,
                        technique: $technique,
                        help: $help,
                        task: $task,
                        transcript: $transcript,
                        reviewed_ids: $reviewed_ids
                    }
                    """,
                    {
                        "user_id": state.user_id,
                        "topic": state.topic,
                        "traits": state.traits.model_dump(),
                        "technique": state.technique.model_dump(),
                        "help": state.help.model_dump(),
                        "task": state.task.model_dump(),
                        "transcript": [t.model_dump() for t in state.transcript],
                        "reviewed_ids": list(state.reviewed_ids),
                    },
                )
            )
        rows = _rows(result)
        if not rows:
            raise RuntimeError("Session record was not created")
        return str(rows[0]["id"])

    async def load(self, session_id: str) -> dict[str, Any]:
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    "SELECT * FROM session WHERE id = <record>$id",
                    {"id": session_id},
                )
            )
        rows = _rows(result)
        if not rows:
            raise UnknownSessionError(session_id)
        return rows[0]

    async def save_progress(self, state: SessionState) -> None:
        async with atenea_db() as db:
            ensure_ok(
                await db.query(
                    """
                    UPDATE session SET
                        help = $help,
                        task = $task,
                        transcript = $transcript,
                        updated_at = time::now()
                    WHERE id = <record>$id
                    """,
                    {
                        "id": state.session_id,
                        "help": state.help.model_dump(),
                        "task": state.task.model_dump(),
                        "transcript": [t.model_dump() for t in state.transcript],
                    },
                )
            )

    async def close(
        self,
        session_id: str,
        summary: str,
        assessment: str,
        next_step: str,
        review_date: datetime,
    ) -> None:
        async with atenea_db() as db:
            ensure_ok(
                await db.query(
                    """
                    UPDATE session SET
                        ended_at = time::now(),
                        updated_at = time::now(),
                        summary = $summary,
                        assessment = $assessment,
                        next_step = $next_step,
                        review_date = <datetime>$review_date
                    WHERE id = <record>$id
                    """,
                    {
                        "id": session_id,
                        "summary": summary,
                        "assessment": assessment,
                        "next_step": next_step,
                        "review_date": review_date.isoformat(),
                    },
                )
            )

    async def list_for_user(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List a user's sessions, newest-updated first (PR-R1).

        `status` is `"open" | "closed" | None`; ORDER BY/field names here are
        static (never bound params — SurrealDB can't parameterize them, see
        docs/7-DEVELOPMENT/security.md), so this stays injection-safe.
        """
        if status == "open":
            status_clause = "AND ended_at IS NONE"
        elif status == "closed":
            status_clause = "AND ended_at IS NOT NONE"
        else:
            status_clause = ""
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    f"""
                    SELECT * FROM session
                    WHERE user_id = $user_id {status_clause}
                    ORDER BY updated_at DESC
                    """,
                    {"user_id": user_id},
                )
            )
        return _rows(result)

    async def due_items(self, user_id: str, now: datetime) -> list[dict[str, Any]]:
        """Closed sessions whose review_date is due, most overdue first (PR-G1).

        Filters in Python over the user's sessions rather than in SurrealQL, so
        it never depends on null/date comparison syntax; a single user's session
        count is small.
        """
        cutoff = _to_naive_utc(now)
        due = [
            r
            for r in await self.list_for_user(user_id)
            if r.get("ended_at")
            and r.get("review_date")
            and _to_naive_utc(r["review_date"]) <= cutoff
        ]
        due.sort(key=lambda r: _to_naive_utc(r["review_date"]))
        return due

    async def record_review(
        self, session_ids: list[str], review_date: datetime, graduate_at: int
    ) -> None:
        """Advance the review lifecycle for each covered item (PR-G1).

        Increments its review_count; once that reaches `graduate_at` the item is
        EVICTED from the review working-set (review_date cleared — the session
        record itself stays for history), otherwise its next review is pushed out
        to `review_date`. This is the update+evict half of cross-session memory:
        material leaves the loop efficiently once it is no longer needed.
        """
        if not session_ids:
            return
        async with atenea_db() as db:
            for sid in session_ids:
                rows = _rows(
                    ensure_ok(
                        await db.query(
                            "SELECT review_count FROM session WHERE id = <record>$id",
                            {"id": sid},
                        )
                    )
                )
                count = int((rows[0].get("review_count") if rows else 0) or 0) + 1
                if count >= graduate_at:
                    ensure_ok(
                        await db.query(
                            """
                            UPDATE session SET
                                review_count = $count,
                                review_date = NONE,
                                updated_at = time::now()
                            WHERE id = <record>$id
                            """,
                            {"id": sid, "count": count},
                        )
                    )
                else:
                    ensure_ok(
                        await db.query(
                            """
                            UPDATE session SET
                                review_count = $count,
                                review_date = <datetime>$review_date,
                                updated_at = time::now()
                            WHERE id = <record>$id
                            """,
                            {
                                "id": sid,
                                "count": count,
                                "review_date": review_date.isoformat(),
                            },
                        )
                    )
