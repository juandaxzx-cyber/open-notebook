"""Material grounding (PR-M1, server-side scoping since PR-M2, whole-source-lite
since PR-W1): anchor a session's retrieval to a chosen source.

Tutor-side seam — calls OpenNotebook's vector search over REST via the
`content.search` tool, passing `source_id` through. Since PR-M2 the core
matches `source_id` DB-side inside `fn::vector_search`, so ranking happens
within the chosen source instead of across the whole corpus; the tool still
keeps only rows belonging to the chosen source client-side too (see
`tutor/tools/content.py`) as defense-in-depth.

PR-W1 whole-source-lite: before falling back to scoped passage search, a
grounded call tries `content.get_source` (REST `full_text`, pulled forward
from the parked M3 slice) and injects the WHOLE source when it fits
`budget_tokens` (NotebookLM lesson — a verifier over partial top-k evidence
produces false fails on claims that ARE in the source, just not in the top-k
chunks). Any failure fetching the whole source (tool unavailable, 404,
network, empty/oversized text) falls back to today's scoped retrieval —
grounding must always degrade safely, never error a session.

`retrieve_grounding` is the single seam the engine calls (once in `open`, once in
`message`). When ungrounded it reproduces the legacy digest byte-for-byte, so
sessions without a chosen source behave exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tutor.tools.registry import ToolRegistry

# server-side scoping since PR-M2: the core already filters to the chosen
# source inside fn::vector_search (migration 23), so this is a normal result
# limit — no more over-fetching across the whole corpus to compensate for
# approximate (tutor-side-only) scoping like PR-M1 had to.
_GROUNDED_LIMIT = 10
_MAX_PASSAGES = 6
_MAX_CHARS = 4000
_DIGEST_ITEMS = 5
_DIGEST_SNIPPET = 300

# PR-W1: default whole-source-lite token budget (provisional per contract);
# engine.py threads the configured value through, this is only the fallback
# for direct callers/tests that don't pass one.
DEFAULT_BUDGET_TOKENS = 16000


@dataclass
class GroundingResult:
    content: str  # rendered block for the {{content}} prompt slot
    source_id: str | None  # anchor persisted on the session (None if ungrounded)
    grounded: bool
    whole_source: bool = False  # PR-W1: whole-source-lite vs scoped passages


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


def _bare_source_id(value: str) -> str:
    """Compare/emit source ids regardless of the 'source:' record-id prefix
    (mirrors `tutor/tools/content.py::_norm_source`)."""
    return value.split(":", 1)[1] if value.startswith("source:") else value


def _estimate_tokens(text: str) -> int:
    """Tutor-side token estimate (contract: "budget in TOKENS per ON
    convention, tutor-side estimate acceptable") — mirrors the word-count
    fallback ON itself falls back to when tiktoken is unavailable
    (open_notebook/utils/token_utils.py::token_count), so the two systems'
    rough magnitudes agree without the tutor importing open_notebook."""
    return int(len(text.split()) * 1.3)


def _format_whole_source(text: str, title: str, source_id: str) -> str:
    bare = _bare_source_id(source_id)
    return (
        f'GROUNDED SOURCE — "{title}" (whole source — it fit the token '
        "budget). Teach strictly from this material; cite it by its record "
        f"id in brackets, exactly as given — [source:{bare}] — never invent "
        "an id, and do not add outside facts this text already covers:\n\n"
        f"[source:{bare}] {text}"
    )


async def _try_whole_source(
    registry: ToolRegistry, source_id: str, budget_tokens: int
) -> str | None:
    """PR-W1 whole-source-lite: fetch the full source and return the
    rendered block if it fits the budget, else ``None`` so the caller falls
    back to scoped retrieval. Any failure (tool not wired, 404, network,
    empty text) is swallowed here — the same "never break a session"
    contract every grounding path follows."""
    try:
        source = await registry.call("content.get_source", {"source_id": source_id})
    except Exception:  # noqa: BLE001 — unknown tool / 404 / network all fall back
        return None
    text = str((source or {}).get("full_text") or "").strip()
    if not text or _estimate_tokens(text) > budget_tokens:
        return None
    title = str((source or {}).get("title") or "the chosen source")
    return _format_whole_source(text, title, source_id)


async def retrieve_grounding(
    registry: ToolRegistry,
    *,
    topic: str,
    source_id: str | None,
    enabled: bool,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> GroundingResult:
    """Single grounding seam for both paths.

    Ungrounded (no source, or feature off): `content.search` is called with only
    ``{query, limit}`` and rendered as the legacy digest — nothing downstream
    changes. Grounded: PR-W1 first tries whole-source-lite (`content.get_source`
    under `budget_tokens`); if that doesn't apply, falls back to a vector
    search scoped to ``source_id`` (matched DB-side inside `fn::vector_search`
    since PR-M2; the `content.search` tool also filters rows by ``parent_id``
    client-side as defense-in-depth) and renders cited passages.

    ``budget_tokens`` is an additive keyword-only parameter (default matches
    the W1 contract's 16000) — the four original parameters are unchanged, so
    every pre-W1 call site keeps working untouched.
    """
    if enabled and source_id:
        whole = await _try_whole_source(registry, source_id, budget_tokens)
        if whole is not None:
            return GroundingResult(
                content=whole, source_id=source_id, grounded=True, whole_source=True
            )
        search = await registry.call(
            "content.search",
            {
                "query": topic,
                "limit": _GROUNDED_LIMIT,
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
