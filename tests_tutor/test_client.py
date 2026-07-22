import asyncio
import json
from typing import Any

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


# --- create_source_from_file / create_source_json (PR-BT3) ---


def test_create_source_from_file_posts_multipart_with_async_processing() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"id": "source:new1", "title": "notes.pdf"})

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    result = asyncio.run(
        client.create_source_from_file(
            "notes.pdf", b"%PDF-1.4 fake", "application/pdf", title="My notes"
        )
    )

    assert seen["path"] == "/api/sources"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b'name="type"' in seen["body"] and b"upload" in seen["body"]
    assert b'name="async_processing"' in seen["body"] and b"true" in seen["body"]
    assert b'name="title"' in seen["body"] and b"My notes" in seen["body"]
    assert b'filename="notes.pdf"' in seen["body"]
    assert result == {"id": "source:new1", "title": "notes.pdf"}


def test_create_source_from_file_omits_title_when_not_given() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"id": "source:new2"})

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    asyncio.run(client.create_source_from_file("a.txt", b"hi"))
    assert b'name="title"' not in seen["body"]


def test_create_source_json_posts_payload_as_is() -> None:
    seen: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path.encode()
        seen["body"] = request.content
        return httpx.Response(200, json={"id": "source:new3"})

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    payload = {"type": "link", "url": "https://example.com", "async_processing": True}
    result = asyncio.run(client.create_source_json(payload))

    assert seen["path"] == b"/api/sources/json"
    assert json.loads(seen["body"]) == payload
    assert result == {"id": "source:new3"}
