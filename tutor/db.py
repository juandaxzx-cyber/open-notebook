"""Async SurrealDB access for the tutor's own `atenea` database.

The tutor shares OpenNotebook's SurrealDB *instance* (same SURREAL_URL,
credentials and namespace) but uses a separate *database* so upstream's
migration chain is never touched. The `surrealdb` import stays contained
in this module (same pattern as the Esperanto adapter).

Connection pattern mirrors open_notebook/database/repository.py, including
the quirk that the client returns error *strings* instead of raising.
Schema is applied idempotently on connect from tutor/schema.surrealql.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).parent / "schema.surrealql"


def surreal_url() -> str:
    return os.environ.get("SURREAL_URL", "ws://localhost:8000/rpc")


def surreal_credentials() -> dict[str, str]:
    return {
        "username": os.environ.get("SURREAL_USER", "root"),
        "password": os.environ.get("SURREAL_PASSWORD", "root"),
    }


def surreal_namespace() -> str:
    return os.environ.get("SURREAL_NAMESPACE", "open_notebook")


def tutor_database() -> str:
    return os.environ.get("TUTOR_SURREAL_DATABASE", "atenea")


def ensure_ok(result: Any) -> Any:
    """Raise if the SurrealDB client returned an error string.

    The client reports query errors as plain strings (see repo_query in
    open_notebook/database/repository.py) — a string where rows were
    expected always means an error.
    """
    if isinstance(result, str):
        raise RuntimeError(f"SurrealDB error: {result}")
    if isinstance(result, list):
        for item in result:
            if isinstance(item, str):
                raise RuntimeError(f"SurrealDB error: {item}")
    return result


@asynccontextmanager
async def atenea_db() -> AsyncIterator[Any]:
    """Yield a SurrealDB connection to the atenea database, schema applied."""
    from surrealdb import AsyncSurreal  # local import: keep surrealdb contained

    db = AsyncSurreal(surreal_url())
    await db.signin(surreal_credentials())
    await db.use(surreal_namespace(), tutor_database())
    ensure_ok(await db.query(SCHEMA_PATH.read_text()))
    try:
        yield db
    finally:
        await db.close()
