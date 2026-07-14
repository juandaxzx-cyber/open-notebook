"""PR-M2 — retrieve_grounding forwards source_id to the client (server-side
scoping), on top of the tutor-side parent_id filter kept as defense-in-depth.

Separate from tests_tutor/test_grounding.py, which is PR-M1's suite and must
stay byte-for-byte unchanged (it already exercises the ungrounded/grounded
formatting behavior; this file only adds the new PR-M2 wiring assertion).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from tutor.clients.open_notebook import OpenNotebookClient
from tutor.session.grounding import retrieve_grounding
from tutor.tools.content import content_search_tool
from tutor.tools.registry import ToolRegistry


def test_retrieve_grounding_forwards_source_id_to_the_client_request_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search":
            seen["body"] = request.content
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Algebra",
                            "content": "A vector is an arrow.",
                            "parent_id": "source:A",
                            "similarity": 0.9,
                        }
                    ],
                    "total_count": 1,
                    "search_type": "vector",
                },
            )
        return httpx.Response(404)

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    registry = ToolRegistry()
    registry.register(content_search_tool(client))

    result = asyncio.run(
        retrieve_grounding(
            registry, topic="vectors", source_id="source:A", enabled=True
        )
    )

    assert result.grounded is True
    body = seen["body"]
    assert b'"source_id": "source:A"' in body or b'"source_id":"source:A"' in body


def test_retrieve_grounding_ungrounded_never_sends_source_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(
            200, json={"results": [], "total_count": 0, "search_type": "text"}
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    registry = ToolRegistry()
    registry.register(content_search_tool(client))

    result = asyncio.run(
        retrieve_grounding(registry, topic="vectors", source_id=None, enabled=True)
    )

    assert result.grounded is False
    assert b"source_id" not in seen["body"]
