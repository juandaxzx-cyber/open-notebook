"""Session persistence over the atenea database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from tutor.db import atenea_db, ensure_ok
from tutor.session.models import SessionState
from tutor.session.scheduling import sm2_next


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


def _seed_interval_days(record: dict[str, Any]) -> float:
    """Pre-G3 compat seed (PR-G3 contract): a record reviewed for the first
    time under G3 has no `review_interval_days` yet. Seed it from the gap
    between when it was closed (`ended_at`) and when its (G1, flat)
    `review_date` was set, so the first SM-2 step isn't a jarring reset;
    falls back to 1.0 day when that gap can't be derived (missing fields,
    non-positive gap, unparseable dates)."""
    ended_at = record.get("ended_at")
    review_date = record.get("review_date")
    if not ended_at or not review_date:
        return 1.0
    try:
        gap = (
            _to_naive_utc(review_date) - _to_naive_utc(ended_at)
        ).total_seconds() / 86400.0
    except Exception:  # noqa: BLE001 — defensive: a bad date must never block a review
        return 1.0
    return gap if gap > 0 else 1.0


class SessionStore:
    async def create(self, state: SessionState) -> str:
        """Persist a new session; returns the record id."""
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    """
                    CREATE session CONTENT {
                        user_id: $user_id,
                        source_id: $source_id,
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
                        "source_id": state.source_id,
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
        self,
        session_ids: list[str],
        grades: dict[str, float],
        now: datetime,
        horizon_days: float,
    ) -> None:
        """Advance the review lifecycle for each covered item (PR-G3):
        per-item SM-2 update from its quality grade (`grades[session_id]`,
        see `tutor.session.scheduling.sm2_next`), then either reschedule
        (`review_date = now + new_interval_days`) or EVICT (new interval
        exceeds `horizon_days` — `review_date` cleared, the session record
        itself stays for history, same as before). Replaces PR-G1's flat
        count-based reschedule/graduation (`GRADUATION_REVIEWS`, removed).

        Pre-G3 records without `ease`/`review_interval_days` get compat
        defaults seeded on this, their first G3-tracked review (see
        `_seed_interval_days`) — no migration needed.
        """
        if not session_ids:
            return
        async with atenea_db() as db:
            for sid in session_ids:
                rows = _rows(
                    ensure_ok(
                        await db.query(
                            """
                            SELECT ease, review_interval_days, review_count,
                                   ended_at, review_date
                            FROM session WHERE id = <record>$id
                            """,
                            {"id": sid},
                        )
                    )
                )
                record = rows[0] if rows else {}
                ease = record.get("ease")
                ease = 2.5 if ease is None else float(ease)
                interval = record.get("review_interval_days")
                interval = (
                    _seed_interval_days(record) if interval is None else float(interval)
                )
                quality = grades.get(sid)
                if quality is None:
                    # Parse-error fallback (contract): schedule as a neutral
                    # q=3 but NEVER evict — cap the interval at the horizon so
                    # the item gets one more real review instead of silently
                    # graduating off an LLM formatting hiccup.
                    new_ease, new_interval, _ = sm2_next(
                        ease, interval, 3.0, horizon_days
                    )
                    new_interval = min(new_interval, horizon_days)
                    evict = False
                else:
                    new_ease, new_interval, evict = sm2_next(
                        ease, interval, quality, horizon_days
                    )
                review_count = int(record.get("review_count") or 0) + 1
                if evict:
                    ensure_ok(
                        await db.query(
                            """
                            UPDATE session SET
                                ease = $ease,
                                review_interval_days = $interval,
                                review_count = $count,
                                review_date = NONE,
                                updated_at = time::now()
                            WHERE id = <record>$id
                            """,
                            {
                                "id": sid,
                                "ease": new_ease,
                                "interval": new_interval,
                                "count": review_count,
                            },
                        )
                    )
                else:
                    new_review_date = now + timedelta(days=new_interval)
                    ensure_ok(
                        await db.query(
                            """
                            UPDATE session SET
                                ease = $ease,
                                review_interval_days = $interval,
                                review_count = $count,
                                review_date = <datetime>$review_date,
                                updated_at = time::now()
                            WHERE id = <record>$id
                            """,
                            {
                                "id": sid,
                                "ease": new_ease,
                                "interval": new_interval,
                                "count": review_count,
                                "review_date": new_review_date.isoformat(),
                            },
                        )
                    )

    # --- consolidated learner memory (PR-G2) ---

    async def list_memories(self, user_id: str) -> list[dict[str, Any]]:
        """This user's consolidated memory notes, most-recently-updated
        first (recency-ranking for `recall`'s "related" notes)."""
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    """
                    SELECT * FROM learner_memory
                    WHERE user_id = $user_id
                    ORDER BY updated DESC
                    """,
                    {"user_id": user_id},
                )
            )
        return _rows(result)

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
        """Create or update the (user_id, topic_key) memory note. Existing
        key ⇒ overwrite the consolidated fields and bump `sessions_count`;
        new key ⇒ a fresh note with `sessions_count = 1` (PR-G2 LLM-keying +
        local-merge contract — the merge decision itself lives here, not in
        the generator prompt)."""
        async with atenea_db() as db:
            existing = _rows(
                ensure_ok(
                    await db.query(
                        """
                        SELECT * FROM learner_memory
                        WHERE user_id = $user_id AND topic_key = $topic_key
                        """,
                        {"user_id": user_id, "topic_key": topic_key},
                    )
                )
            )
            if existing:
                record_id = existing[0]["id"]
                sessions_count = int(existing[0].get("sessions_count") or 0) + 1
                # PR-G3: strength rises with each successful consolidation
                # touch on the topic — a simple bounded rule (+0.5 per
                # touch, capped at 5.0) so `retention()` (read-time, in
                # /memories) sees a slower decay the more a topic has been
                # reinforced. Not itself a mastery signal — mastery_estimate
                # already covers "how well", this covers "how durable".
                strength = min(float(existing[0].get("strength") or 1.0) + 0.5, 5.0)
                result = ensure_ok(
                    await db.query(
                        """
                        UPDATE learner_memory SET
                            topic_label = $topic_label,
                            summary = $summary,
                            mastery_estimate = $mastery_estimate,
                            recurring_errors = $recurring_errors,
                            sessions_count = $sessions_count,
                            strength = $strength,
                            last_session_id = $last_session_id,
                            updated = time::now()
                        WHERE id = <record>$id
                        """,
                        {
                            "id": record_id,
                            "topic_label": topic_label,
                            "summary": summary,
                            "mastery_estimate": mastery_estimate,
                            "recurring_errors": recurring_errors,
                            "sessions_count": sessions_count,
                            "strength": strength,
                            "last_session_id": last_session_id,
                        },
                    )
                )
            else:
                result = ensure_ok(
                    await db.query(
                        """
                        CREATE learner_memory CONTENT {
                            user_id: $user_id,
                            topic_key: $topic_key,
                            topic_label: $topic_label,
                            summary: $summary,
                            mastery_estimate: $mastery_estimate,
                            recurring_errors: $recurring_errors,
                            sessions_count: 1,
                            last_session_id: $last_session_id
                        }
                        """,
                        {
                            "user_id": user_id,
                            "topic_key": topic_key,
                            "topic_label": topic_label,
                            "summary": summary,
                            "mastery_estimate": mastery_estimate,
                            "recurring_errors": recurring_errors,
                            "last_session_id": last_session_id,
                        },
                    )
                )
        rows = _rows(result)
        if not rows:
            raise RuntimeError("learner_memory upsert did not return a row")
        return rows[0]
