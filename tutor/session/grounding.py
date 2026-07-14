"""Material grounding (PR-M1): anchor a session's retrieval to a chosen source.

Tutor-side only — reuses OpenNotebook's existing vector search over REST via the
`content.search` tool, then keeps only rows belonging to the chosen source
(every `fn::vector_search` row carries `parent_id = source.id`). No core change;
PR-M2 moves the source filter into the core search behind this same function.

`retrieve_grounding` is the single seam the engine calls (once in `open`, once in
`message`). When ungrounded it reproduces the legacy digest byte-for-byte, so
sessions without a chosen source behave exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tutor.tools.registry import ToolRegistry

# The core vector search is global (no source filter until PR-M2), so for a
# source-scoped session we over-fetch and keep the chosen source's rows.
# Accepted PR-M1 limitation: if the source ranks low globally, raise this.
_OVERFETCH = 40
_MAX_PASSAGES = 6
_MAX_CHARS = 4000
_DIGEST_ITEMS = 5
_DIGEST_SNIPPET = 300


@dataclass
class GroundingResult:
    content: str  # rendered block for the {{content}} prompt slot
    source_id: str | None  # anchor persisted on the session (None if ungrounded)
    grounded: bool


def _digest(search: dict[str, Any]) -> str:
    """Legacy top-N snippet digest — unchanged behavior for ungrounded sessions."""
    items = (search.get("results") or [])[:_DIGEST_ITEMS]
    if not items:
        return "(no material found for this topic)"
    lines = []
    for item in items:
        title = str(item.get("title") or item.get("id") or "untitled")
        snippet = str(item.get("content") or item.get("matches") or "")[
            :_DIGEST_SNIPPET
        ]
        lines.append(f"- {title}: {snippet}")
    return "\n".join(lines)


def _format_grounded(rows: list[dict[str, Any]], source_id: str) -> str:
    if not rows:
        return (
            f"GROUNDED SOURCE (id {source_id}): no passages matched this topic in "
            "the chosen source. Say so plainly and ask the learner which part of "
            "the material they want to work on."
        )
    title = str(rows[0].get("title") or "the chosen source")
    parts = [
        f'GROUNDED SOURCE — "{title}". Teach from these passages; quote and cite '
        "them by their [n] marker, and do not rely on outside facts when a passage "
        "covers the point:"
    ]
    used = 0
    for i, row in enumerate(rows[:_MAX_PASSAGES], start=1):
        text = str(row.get("content") or "").strip()
        if not text:
            continue
        if used + len(text) > _MAX_CHARS:
            text = text[: max(0, _MAX_CHARS - used)]
        if not text:
            break
        parts.append(f"[{i}] {text}")
        used += len(text)
        if used >= _MAX_CHARS:
            break
    return "\n\n".join(parts)


async def retrieve_grounding(
    registry: ToolRegistry,
    *,
    topic: str,
    source_id: str | None,
    enabled: bool,
) -> GroundingResult:
    """Single grounding seam for both paths.

    Ungrounded (no source, or feature off): `content.search` is called with only
    ``{query, limit}`` and rendered as the legacy digest — nothing downstream
    changes. Grounded: over-fetch a vector search scoped to ``source_id`` (the
    `content.search` tool filters rows by ``parent_id``) and render cited passages.
    """
    if enabled and source_id:
        search = await registry.call(
            "content.search",
            {
                "query": topic,
                "limit": _OVERFETCH,
                "type": "vector",
                "source_id": source_id,
            },
        )
        rows = search.get("results") or []
        return GroundingResult(
            content=_format_grounded(rows, source_id),
            source_id=source_id,
            grounded=True,
        )
    search = await registry.call(
        "content.search", {"query": topic, "limit": _DIGEST_ITEMS}
    )
    return GroundingResult(content=_digest(search), source_id=None, grounded=False)
