import asyncio

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
