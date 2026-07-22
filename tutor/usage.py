"""Daily turn cap: `usage_counter` table + the `usage` CLI verb (PR-BT2).

One seam, kept separate from `tutor/session/store.py` (implementer's call,
logged in the PR description): mirrors the `AccessTokenStore` /
`AccessTokenStoreProtocol` split in `tutor/auth.py` — a small typed store
plus a Protocol so `engine.message` and tests can inject an in-memory double
without touching SurrealDB (same pattern as
`tutor.eval.fakes.InMemorySessionStore`).

`engine.message` increments the requester's counter for the current UTC day
and enforces `TUTOR_DAILY_TURN_CAP` BEFORE calling the LLM (contract:
`tutor/session/engine.py::message`). `TUTOR_DAILY_TURN_CAP=0` means
unlimited — the engine's default constructor value (0) skips this seam
entirely (never touches the store), the same "additive, off ⇒ untouched"
pattern as `TUTOR_AUTH_ENABLED`/`TUTOR_GROUNDING_ENABLED`; `app.py` wires the
real cap (default 50) and a real `UsageCounterStore` for the live service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from tutor.db import atenea_db, ensure_ok


class DailyCapExceededError(RuntimeError):
    """Raised by `engine.message` when a user's turn count for the current
    UTC day has already reached `TUTOR_DAILY_TURN_CAP`. Mapped to 429 by
    `tutor/session/router.py`."""

    def __init__(self, user_id: str, day: str, cap: int) -> None:
        self.user_id = user_id
        self.day = day
        self.cap = cap
        super().__init__(
            f"Daily turn cap ({cap}) exceeded for user {user_id!r} on {day}."
        )


def today_utc() -> str:
    """UTC calendar day as YYYY-MM-DD — the `usage_counter.day` key."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class UsageCounterStoreProtocol(Protocol):
    """The slice `engine.message` and the `usage` CLI verb need — satisfied
    by `UsageCounterStore` and any in-memory test double."""

    async def increment(self, user_id: str, day: str) -> int:
        """Atomically bump this user's turn count for `day`; returns the new
        total (the value enforcement compares against the cap)."""
        ...

    async def usage(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Raw `(user_id, day, turns)` rows, optionally scoped to one user;
        the CLI aggregates per-user totals from these."""
        ...


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        if result and isinstance(result[0], list):
            return [r for r in result[0] if isinstance(r, dict)]
        return [r for r in result if isinstance(r, dict)]
    return []


class UsageCounterStore:
    """CRUD over the `usage_counter` table (atenea DB)."""

    async def increment(self, user_id: str, day: str) -> int:
        async with atenea_db() as db:
            existing = _rows(
                ensure_ok(
                    await db.query(
                        """
                        SELECT * FROM usage_counter
                        WHERE user_id = $user_id AND day = $day
                        LIMIT 1
                        """,
                        {"user_id": user_id, "day": day},
                    )
                )
            )
            if existing:
                result = ensure_ok(
                    await db.query(
                        """
                        UPDATE usage_counter SET turns = turns + 1
                        WHERE id = <record>$id
                        """,
                        {"id": existing[0]["id"]},
                    )
                )
            else:
                result = ensure_ok(
                    await db.query(
                        """
                        CREATE usage_counter CONTENT {
                            user_id: $user_id,
                            day: $day,
                            turns: 1
                        }
                        """,
                        {"user_id": user_id, "day": day},
                    )
                )
        rows = _rows(result)
        if not rows:
            raise RuntimeError("usage_counter increment did not return a row")
        return int(rows[0]["turns"])

    async def usage(self, user_id: str | None = None) -> list[dict[str, Any]]:
        async with atenea_db() as db:
            if user_id:
                result = ensure_ok(
                    await db.query(
                        """
                        SELECT * FROM usage_counter
                        WHERE user_id = $user_id
                        ORDER BY day DESC
                        """,
                        {"user_id": user_id},
                    )
                )
            else:
                result = ensure_ok(
                    await db.query(
                        "SELECT * FROM usage_counter ORDER BY user_id, day DESC"
                    )
                )
        return _rows(result)
