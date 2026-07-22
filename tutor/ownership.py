"""Tutor-side source ownership (PR-BT3 contract): makes uploaded sources
private without any OpenNotebook core change.

Table `source_owner` (atenea DB): `source_id` (unique index), `user_id`
(indexed), `public` (bool, default false), `created`. **Grandfather
clause: a source_id with NO row is PUBLIC** — the pre-BT curated corpus
stays visible to every tester. Only sources created THROUGH the tutor
(`POST /sources/upload`, `POST /sources/create`) ever get a row, written
private (owner = the requester) at creation time. Sharing (flipping
`public` to true) is CLI-only this slice: `python -m tutor.access share
<source_id>`.

Same Protocol + Surreal-impl + in-memory-fake split as
`tutor/auth.py::AccessTokenStore` / `tutor/usage.py::UsageCounterStore`
(the in-memory fake lives in `tutor/eval/fakes.py`, same convention).
"""

from __future__ import annotations

from typing import Any, Protocol

from tutor.db import atenea_db, ensure_ok


def normalize_source_id(value: Any) -> str:
    """Compare/store source ids regardless of the 'source:' record-id
    prefix. Same normalization `tutor/tools/content.py::_norm_source` and
    `tutor/session/grounding.py::_bare_source_id` already use for the same
    reason (OpenNotebook returns ids as "source:<key>"; callers — the UI
    picker, `retrieve_grounding`'s `source_id`, the upload proxy's created
    id — may pass either form)."""
    text = str(value or "")
    return text.split(":", 1)[1] if text.startswith("source:") else text


class SourceOwnerStoreProtocol(Protocol):
    """The slice `TutorEngine` (grounding visibility), the `/sources`
    picker proxy, the upload/create endpoints, and the `tutor.access
    share` CLI verb need — satisfied by `SourceOwnerStore` and any
    in-memory test double."""

    async def create(
        self, source_id: str, user_id: str, public: bool = False
    ) -> None: ...

    async def get(self, source_id: str) -> dict[str, Any] | None: ...

    async def is_visible(self, source_id: str, user_id: str) -> bool: ...

    async def share(self, source_id: str) -> bool: ...

    async def list_all(self) -> list[dict[str, Any]]: ...


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        if result and isinstance(result[0], list):
            return [r for r in result[0] if isinstance(r, dict)]
        return [r for r in result if isinstance(r, dict)]
    return []


class SourceOwnerStore:
    """CRUD over the `source_owner` table (atenea DB)."""

    async def create(self, source_id: str, user_id: str, public: bool = False) -> None:
        key = normalize_source_id(source_id)
        async with atenea_db() as db:
            ensure_ok(
                await db.query(
                    """
                    CREATE source_owner CONTENT {
                        source_id: $source_id,
                        user_id: $user_id,
                        public: $public
                    }
                    """,
                    {"source_id": key, "user_id": user_id, "public": public},
                )
            )

    async def get(self, source_id: str) -> dict[str, Any] | None:
        key = normalize_source_id(source_id)
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    "SELECT * FROM source_owner WHERE source_id = $source_id LIMIT 1",
                    {"source_id": key},
                )
            )
        rows = _rows(result)
        return rows[0] if rows else None

    async def is_visible(self, source_id: str, user_id: str) -> bool:
        """Grandfather clause: no row => public => visible to everyone.
        Otherwise visible iff the row is public or the requester owns it."""
        row = await self.get(source_id)
        if row is None:
            return True
        if bool(row.get("public")):
            return True
        return str(row.get("user_id")) == user_id

    async def share(self, source_id: str) -> bool:
        """Flip `public` to true — the `tutor.access share` CLI verb.
        Returns False when there is nothing to flip (no row at all, i.e.
        the source is already public via the grandfather clause, or the
        row is already public); True on an actual change."""
        key = normalize_source_id(source_id)
        row = await self.get(key)
        if row is None or bool(row.get("public")):
            return False
        async with atenea_db() as db:
            ensure_ok(
                await db.query(
                    "UPDATE source_owner SET public = true WHERE source_id = $source_id",
                    {"source_id": key},
                )
            )
        return True

    async def list_all(self) -> list[dict[str, Any]]:
        """Every ownership row — the `/sources` picker's single lookup for
        filtering the requester's visible set (own + public)."""
        async with atenea_db() as db:
            result = ensure_ok(await db.query("SELECT * FROM source_owner"))
        return _rows(result)
