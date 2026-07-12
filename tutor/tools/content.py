"""content.search — retrieve study material from OpenNotebook."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from tutor.clients.open_notebook import OpenNotebookClient
from tutor.tools.registry import ToolSpec


class ContentSearchInput(BaseModel):
    query: str = Field(min_length=1, description="What to look for")
    limit: int = Field(10, ge=1, le=100, description="Max results")
    type: Literal["text", "vector"] = Field(
        "text", description="text = keyword search, vector = semantic search"
    )


def content_search_tool(client: OpenNotebookClient) -> ToolSpec:
    async def handler(args: ContentSearchInput) -> dict[str, Any]:
        return await client.search(
            query=args.query, limit=args.limit, search_type=args.type
        )

    return ToolSpec(
        name="content.search",
        description=(
            "Search the learner's indexed study material (sources and notes "
            "in OpenNotebook). Returns matching items with relevance scores. "
            "Use this before explaining a topic, to ground the session in the "
            "learner's own material."
        ),
        input_model=ContentSearchInput,
        handler=handler,
    )
