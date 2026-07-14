"""content.search — retrieve study material from OpenNotebook.

PR-M1 added an optional ``source_id`` that scoped results to a single source
by filtering tutor-side (every `fn::vector_search` row carries
``parent_id = source.id``). PR-M2 forwards ``source_id`` to the client so the
core does the filtering DB-side, inside ``fn::vector_search`` (ranking then
happens within the source, not over the whole corpus); the tutor-side
``parent_id`` filter below is kept as defense-in-depth so this tool degrades
safely against an older core that ignores ``source_id``.
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
        # source_id since PR-M2: forwarded to the client, which sends it to
        # the core API for DB-side scoping (see tutor/clients/open_notebook.py).
        result = await client.search(
            query=args.query,
            limit=args.limit,
            search_type=args.type,
            source_id=args.source_id,
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
