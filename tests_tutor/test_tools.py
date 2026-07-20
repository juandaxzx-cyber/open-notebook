import asyncio
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.profile.models import Profile, ProfileIn
from tutor.profile.service import ProfileService
from tutor.tools.content import content_search_tool
from tutor.tools.defaults import build_default_registry
from tutor.tools.profile_tools import profile_read_tool, profile_write_tool
from tutor.tools.registry import (
    DuplicateToolError,
    ToolRegistry,
    ToolSpec,
    UnknownToolError,
)


class EchoInput(BaseModel):
    text: str


def _echo_spec(name: str = "test.echo") -> ToolSpec:
    async def handler(args: EchoInput) -> str:
        return args.text.upper()

    return ToolSpec(
        name=name, description="Echo", input_model=EchoInput, handler=handler
    )


class FakeProfileService(ProfileService):
    def __init__(self) -> None:
        self.stored: dict[str, Profile] = {}

    async def get_profile(self, user_id: str) -> Profile | None:
        return self.stored.get(user_id)

    async def upsert_profile(self, user_id: str, payload: ProfileIn) -> Profile:
        profile = Profile(user_id=user_id, **payload.model_dump())
        self.stored[user_id] = profile
        return profile


def test_registry_register_call_and_list() -> None:
    registry = ToolRegistry()
    registry.register(_echo_spec())

    specs = registry.list_specs()
    assert [s["name"] for s in specs] == ["test.echo"]
    assert "text" in specs[0]["input_schema"]["properties"]

    result = asyncio.run(registry.call("test.echo", {"text": "hola"}))
    assert result == "HOLA"


def test_registry_rejects_duplicates_and_unknown_tools() -> None:
    registry = ToolRegistry()
    registry.register(_echo_spec())
    with pytest.raises(DuplicateToolError):
        registry.register(_echo_spec())
    with pytest.raises(UnknownToolError):
        registry.get("nope")


def test_registry_validates_arguments() -> None:
    registry = ToolRegistry()
    registry.register(_echo_spec())
    with pytest.raises(Exception):  # pydantic ValidationError
        asyncio.run(registry.call("test.echo", {"wrong": 1}))


def test_content_search_tool_calls_open_notebook() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={"results": [{"title": "t"}], "total_count": 1, "search_type": "text"},
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    spec = content_search_tool(client)

    registry = ToolRegistry()
    registry.register(spec)
    result = asyncio.run(registry.call("content.search", {"query": "algebra"}))

    assert seen["path"] == "/api/search"
    assert b'"query": "algebra"' in seen["body"] or b'"query":"algebra"' in seen["body"]
    assert result["total_count"] == 1


def test_content_search_tool_forwards_source_id_to_client() -> None:
    # PR-M2: source_id must reach the HTTP request body (server-side scoping
    # inside fn::vector_search), not just the tutor-side parent_id filter.
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "results": [{"title": "t", "parent_id": "source:A"}],
                "total_count": 1,
                "search_type": "vector",
            },
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    spec = content_search_tool(client)
    registry = ToolRegistry()
    registry.register(spec)

    asyncio.run(
        registry.call(
            "content.search",
            {"query": "algebra", "type": "vector", "source_id": "source:A"},
        )
    )

    assert b'"source_id": "source:A"' in seen["body"] or (
        b'"source_id":"source:A"' in seen["body"]
    )


def test_content_search_tool_omits_source_id_from_client_when_unset() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(
            200, json={"results": [], "total_count": 0, "search_type": "text"}
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    spec = content_search_tool(client)
    registry = ToolRegistry()
    registry.register(spec)

    asyncio.run(registry.call("content.search", {"query": "algebra"}))

    assert b"source_id" not in seen["body"]


def test_profile_tools_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_USER_ID", "juanda")
    service = FakeProfileService()
    registry = ToolRegistry()
    registry.register(profile_read_tool(service))
    registry.register(profile_write_tool(service))

    assert asyncio.run(registry.call("profile.read", {})) is None

    written = asyncio.run(
        registry.call(
            "profile.write",
            {
                "learning_goal": "surrealql",
                "self_assessed_level": "beginner",
                "weekly_availability_hours": 4,
            },
        )
    )
    assert written["user_id"] == "juanda"

    read_back = asyncio.run(registry.call("profile.read", {}))
    assert read_back is not None
    assert read_back["learning_goal"] == "surrealql"


def test_default_registry_lists_all_default_entries() -> None:
    registry = build_default_registry(TutorSettings())
    names = [s["name"] for s in registry.list_specs()]
    # PR-W1 adds content.get_source (whole-source-lite grounding).
    assert names == [
        "content.search",
        "content.get_source",
        "profile.read",
        "profile.write",
    ]
