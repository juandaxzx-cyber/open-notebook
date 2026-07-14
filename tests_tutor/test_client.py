import asyncio
import json

import httpx

from tutor.clients.open_notebook import OpenNotebookClient


def test_count_sources_sends_bearer_auth_and_counts() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        seen["path"] = request.url.path
        return httpx.Response(200, json=[{"id": "source:1"}, {"id": "source:2"}])

    client = OpenNotebookClient(
        base_url="http://open-notebook:5055/",
        password="pw",
        transport=httpx.MockTransport(handler),
    )
    count = asyncio.run(client.count_indexed_sources())

    assert count == 2
    assert seen["auth"] == "Bearer pw"
    assert seen["path"] == "/api/sources"


def test_no_auth_header_without_password() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json=[])

    client = OpenNotebookClient(
        base_url="http://open-notebook:5055",
        transport=httpx.MockTransport(handler),
    )
    count = asyncio.run(client.count_indexed_sources())

    assert count == 0
    assert seen["auth"] == ""


# --- source_id scoping (PR-M2) ---


def test_search_includes_source_id_in_payload_when_set() -> None:
    seen: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(
            200, json={"results": [], "total_count": 0, "search_type": "vector"}
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    asyncio.run(
        client.search(
            "algebra", limit=5, search_type="vector", source_id="source:abc123"
        )
    )

    body = json.loads(seen["body"])
    assert body["source_id"] == "source:abc123"


def test_search_omits_source_id_from_payload_when_none() -> None:
    seen: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(
            200, json={"results": [], "total_count": 0, "search_type": "text"}
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    asyncio.run(client.search("algebra"))

    body = json.loads(seen["body"])
    assert "source_id" not in body
