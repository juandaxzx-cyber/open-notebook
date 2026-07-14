"""content.search — retrieve study material from OpenNotebook.

PR-M1: an optional ``source_id`` scopes results to a single source. Every
`fn::vector_search` row already carries ``parent_id = source.id``, so the filter
runs tutor-side (no core change); PR-M2 moves it into the core search.
"""

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
    source_id: str | None = Field(
        None,
        description="If set, keep only results from this source (parent_id match).",
    )


def _norm_source(value: Any) -> str:
    """Compare source ids regardless of the 'source:' record-id prefix."""
    text = str(value or "")
    return text.split(":", 1)[1] if text.startswith("source:") else text


def _filter_by_source(result: dict[str, Any], source_id: str) -> dict[str, Any]:
    target = _norm_source(source_id)
    rows = [
        r
        for r in (result.get("results") or [])
        if _norm_source(r.get("parent_id")) == target
    ]
    return {**result, "results": rows, "total_count": len(rows)}


def content_search_tool(client: OpenNotebookClient) -> ToolSpec:
    async def handler(args: ContentSearchInput) -> dict[str, Any]:
        result = await client.search(
            query=args.query, limit=args.limit, search_type=args.type
        )
        if args.source_id:
            result = _filter_by_source(result, args.source_id)
        return result

    return ToolSpec(
        name="content.search",
        description=(
            "Search the learner's indexed study material (sources and notes "
            "in OpenNotebook). Returns matching items with relevance scores. "
            "Use this before explaining a topic, to ground the session in the "
            "learner's own material. Pass source_id to scope to one source."
        ),
        input_model=ContentSearchInput,
        handler=handler,
    )
