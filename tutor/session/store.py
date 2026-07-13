"""Session persistence over the atenea database."""

from datetime import datetime
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
                        transcript: $transcript
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
                        transcript = $transcript
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
