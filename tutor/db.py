"""Async SurrealDB access for the tutor's own `atenea` database.

The tutor shares OpenNotebook's SurrealDB *instance* (same SURREAL_URL,
credentials and namespace) but uses a separate *database* so upstream's
migration chain is never touched. The `surrealdb` import stays contained
in this module (same pattern as the Esperanto adapter).

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


@asynccontextmanager
async def atenea_db() -> AsyncIterator[Any]:
    """Yield a SurrealDB connection to the atenea database, schema applied."""
    from surrealdb import AsyncSurreal  # local import: keep surrealdb contained

    async with AsyncSurreal(surreal_url()) as db:
        await db.signin(surreal_credentials())
        await db.use(surreal_namespace(), tutor_database())
        await db.query(SCHEMA_PATH.read_text())
        yield db
