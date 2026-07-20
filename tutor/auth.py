"""Per-request identity: magic-link bearer tokens (PR-BT1 contract).

One seam: `resolve_user`, a FastAPI dependency built per-app by
`build_resolve_user`. Resolution order: `Authorization: Bearer <token>`
header, else the `t` query param (magic-link landing).

`TUTOR_AUTH_ENABLED=false` (default) => returns `default_user_id()`,
byte-identical to pre-BT1 single-tenant behavior (lock test) and never
touches the token store. `true` => a missing/invalid/revoked token is a 401
JSON error (FastAPI's default `{"detail": ...}` shape, same pattern as every
other error path in this service).

Raw tokens are NEVER stored or logged — only their SHA-256 hash. `create` /
`get_by_hash` predate the CLI (PR-BT1, so tests and dogfood could seed a
token before BT2 existed); `list_all` / `revoke` (PR-BT2) are the extra
store methods `python -m tutor.access` builds on (sharing is PR-BT3).
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Protocol

from fastapi import Header, HTTPException, Query

from tutor.config import TutorSettings
from tutor.db import atenea_db, ensure_ok
from tutor.profile.models import default_user_id


def hash_token(raw: str) -> str:
    """SHA-256 hex digest of a raw token. The raw value is never persisted
    or logged — only this hash is looked up / stored."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """A fresh 32-byte urlsafe token (also used by PR-BT2's `create` CLI)."""
    return secrets.token_urlsafe(32)


class AccessTokenStoreProtocol(Protocol):
    """The slice `resolve_user` needs — satisfied by `AccessTokenStore` and
    any in-memory test double (same pattern as `memory.MemoryStoreProtocol`)."""

    async def get_by_hash(self, token_hash: str) -> dict[str, Any] | None: ...


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        if result and isinstance(result[0], list):
            return [r for r in result[0] if isinstance(r, dict)]
        return [r for r in result if isinstance(r, dict)]
    return []


class AccessTokenStore:
    """CRUD over the `access_token` table (atenea DB).

    Full provisioning (list/revoke/usage, the `tutor.access` CLI) is PR-BT2
    scope. `create`/`get_by_hash` are kept minimal here because the schema
    (and this module's own tests) need a way to mint and resolve a token
    without waiting on that CLI.
    """

    async def create(self, user_id: str, label: str = "") -> str:
        """Create a row and return the RAW token — returned exactly once,
        never stored or logged; only its hash is persisted."""
        raw = generate_token()
        async with atenea_db() as db:
            ensure_ok(
                await db.query(
                    """
                    CREATE access_token CONTENT {
                        user_id: $user_id,
                        token_hash: $token_hash,
                        label: $label,
                        revoked: false
                    }
                    """,
                    {
                        "user_id": user_id,
                        "token_hash": hash_token(raw),
                        "label": label,
                    },
                )
            )
        return raw

    async def get_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    "SELECT * FROM access_token WHERE token_hash = $token_hash LIMIT 1",
                    {"token_hash": token_hash},
                )
            )
        rows = _rows(result)
        return rows[0] if rows else None

    async def list_all(self) -> list[dict[str, Any]]:
        """Every provisioned token, newest first — the `tutor.access list`
        CLI verb (PR-BT2). Raw tokens are never stored, so this only ever
        surfaces `user_id`/`label`/`created`/`revoked` (plus the hash, which
        the CLI does not print)."""
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query("SELECT * FROM access_token ORDER BY created DESC")
            )
        return _rows(result)

    async def revoke(self, user_id_or_label: str) -> int:
        """Mark every not-yet-revoked token matching `user_id_or_label` (by
        `user_id` OR `label`) as revoked; returns how many rows changed. The
        `tutor.access revoke` CLI verb (PR-BT2) reports 0 as "nothing to
        revoke" rather than an error — revoking twice is a no-op, not a
        failure."""
        async with atenea_db() as db:
            result = ensure_ok(
                await db.query(
                    """
                    UPDATE access_token SET revoked = true
                    WHERE (user_id = $key OR label = $key) AND revoked = false
                    """,
                    {"key": user_id_or_label},
                )
            )
        return len(_rows(result))


def default_resolve_user() -> Any:
    """Fallback dependency when a router is built without an explicit
    resolver (defensive default; `create_app` always passes a real one built
    from settings, so this path is not exercised by the service itself)."""

    async def resolve_user() -> str:
        return default_user_id()

    return resolve_user


def build_resolve_user(
    settings: TutorSettings, store: AccessTokenStoreProtocol | None = None
) -> Any:
    """Build the `resolve_user` FastAPI dependency for one app instance.

    `TUTOR_AUTH_ENABLED=false` (default): returns `default_user_id()` and
    never touches `store` — byte-identical to pre-BT1 behavior (lock test).
    `true`: resolves `Authorization: Bearer <token>` (preferred) or the `t`
    query param against the token store; missing/invalid/revoked => 401.
    """
    token_store: AccessTokenStoreProtocol = store or AccessTokenStore()

    async def resolve_user(
        authorization: str | None = Header(default=None),
        t: str | None = Query(default=None),
    ) -> str:
        if not settings.auth_enabled:
            return default_user_id()

        raw: str | None = None
        if authorization:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() == "bearer" and value.strip():
                raw = value.strip()
        if not raw and t:
            raw = t
        if not raw:
            raise HTTPException(status_code=401, detail="Missing access token.")

        row = await token_store.get_by_hash(hash_token(raw))
        if row is None or row.get("revoked"):
            raise HTTPException(
                status_code=401, detail="Invalid or revoked access token."
            )
        return str(row["user_id"])

    return resolve_user
