"""Additive, upstream-style guard for PR-M2 (source-scoped vector search).

Pydantic/signature-level assertions only — no DB access, no live SurrealDB
required. This exists because the actual DB-side filter (migration 23 /
fn::vector_search) can't be executed in the Atenea dev sandbox, which has no
live SurrealDB instance; this file is the CI-side gate (GitHub Actions runs
tests/ on Python 3.12 via uv) on the core change described in
CORE_CHANGES.md ("Source-scoped vector search").

open_notebook.domain.notebook pulls in the full core dependency stack
(loguru, surrealdb, surreal_commands, ...), which is not installed in this
sandbox's system python3.10 (only the tutor/ dependency subset is). Skip
gracefully rather than fail when that import errors, so this file is silent
noise locally and a real gate on CI.
"""

import inspect

import pytest

from api.models import SearchRequest

notebook = pytest.importorskip(
    "open_notebook.domain.notebook",
    reason=(
        "open_notebook.domain.notebook needs the full core dependency stack "
        "(loguru, surrealdb, ...), not installed in this sandbox; runs on "
        "GitHub CI (Python 3.12 / uv), which already runs the rest of tests/."
    ),
)


def test_search_request_accepts_source_id_defaulting_to_none() -> None:
    request = SearchRequest(query="algebra", type="vector")
    assert request.source_id is None

    scoped = SearchRequest(query="algebra", type="vector", source_id="source:abc123")
    assert scoped.source_id == "source:abc123"


def test_vector_search_signature_has_source_id_default_none() -> None:
    sig = inspect.signature(notebook.vector_search)
    assert "source_id" in sig.parameters
    assert sig.parameters["source_id"].default is None
