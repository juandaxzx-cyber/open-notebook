"""Consolidated learner memory (PR-G2): the durable, per-topic "how far
you've come" summary, distinct from per-session records (PR-G1's due-review
queue) or the transcript itself.

One seam, two functions — the whole feature lives behind these two entry
points and the engine calls each exactly once (`recall` in `open`/`open_review`,
`consolidate` in `close`):

* `recall` — the topic's note plus up to 2 related notes (recency-ranked),
  for prompt injection. Empty context if disabled or nothing is stored yet.
* `consolidate` — reflect on a just-closed episode into a verified memory
  note. Non-fatal on ANY failure (log + continue): a close must never be
  lost to a bad reflection.

Consolidation is LLM-keyed with local merge (developer decision 2026-07-18):
the generator LLM proposes `{topic_key, topic_label, summary,
mastery_estimate, recurring_errors}`; this module decides whether that key
matches an existing note (upsert) or starts a new one — the generator never
sees or merges prior note content itself, only the compact list of existing
`{topic_key, topic_label}` pairs (kept small on purpose).

Verification: every note is claim-checked against the episode (`verify_memory.md`)
before it is persisted. A failing note is regenerated ONCE with the verifier
acting as generator, violations injected as constraints; a second failure
means the write is skipped entirely (logged), never a bad note silently kept.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tutor.llm.interface import ChatMessage, LLMProvider
from tutor.session.models import SessionState

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Up to 2 related notes injected alongside the topic's own note (contract).
_RELATED_LIMIT = 2


class MemoryStoreProtocol(Protocol):
    """The slice of the store this module needs — satisfied structurally by
    `tutor.session.store.SessionStore` (and any in-memory test double)."""

    async def list_memories(self, user_id: str) -> list[dict[str, Any]]: ...

    async def upsert_memory(
        self,
        user_id: str,
        topic_key: str,
        topic_label: str,
        summary: str,
        mastery_estimate: float,
        recurring_errors: list[str],
        last_session_id: str | None,
    ) -> dict[str, Any]: ...


def _render(template_name: str, values: dict[str, str]) -> str:
    text = (PROMPTS_DIR / template_name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in LLM response: {text[:200]}")
    result: dict[str, Any] = json.loads(match.group(0))
    return result


def normalize_topic_key(topic: str) -> str:
    """Deterministic fallback key: a normalized slug of the session topic,
    used when the generator's JSON is malformed and by `recall` to look up
    the topic's own note (no LLM call happens at recall time)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (topic or "").strip().lower()).strip("-")
    return slug or "general"


def _clamp01(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, f))


def _format_note(note: dict[str, Any], label: str) -> str:
    mastery: Any = note.get("mastery_estimate")
    try:
        mastery_text = f"{float(mastery):.2f}"
    except (TypeError, ValueError):
        mastery_text = "unknown"
    errors = [str(e) for e in (note.get("recurring_errors") or [])]
    errors_text = "; ".join(errors) if errors else "none noted"
    topic_label = note.get("topic_label") or note.get("topic_key") or "?"
    sessions_count = int(note.get("sessions_count") or 0)
    return (
        f'- {label}: "{topic_label}" (mastery ~{mastery_text}, '
        f"{sessions_count} session(s) so far)\n"
        f"  summary: {note.get('summary') or '—'}\n"
        f"  recurring errors: {errors_text}"
    )


@dataclass
class LearnerMemoryContext:
    """Recall result for prompt injection — empty when disabled or nothing
    is stored yet (the byte-identical no-memory path)."""

    note: dict[str, Any] | None = None
    related: list[dict[str, Any]] = field(default_factory=list)

    @property
    def content(self) -> str:
        """Rendered system-prompt section; "" when there is nothing to
        show — this is what keeps disabled/empty sessions byte-identical to
        the pre-G2 prompt (backward-compat lock)."""
        if self.note is None and not self.related:
            return ""
        blocks = []
        if self.note is not None:
            blocks.append(_format_note(self.note, "This topic, from before"))
        for i, rel in enumerate(self.related, start=1):
            blocks.append(_format_note(rel, f"Also worked on recently ({i})"))
        body = "\n".join(blocks)
        return (
            "\n## Learner memory (your history with this learner)\n"
            f"{body}\n\n"
            "Use this pedagogically to decide where to start, which gaps to "
            "close, and to watch for a recurring error you already know "
            "about. Do not recite it verbatim to the learner."
        )


async def recall(
    store: MemoryStoreProtocol,
    user_id: str,
    topic: str,
    enabled: bool,
) -> LearnerMemoryContext:
    """The topic's note plus up to 2 related notes (recency-ranked); empty
    context if disabled or nothing is stored yet. Non-fatal on lookup
    failure — recall must never block a session from opening."""
    if not enabled:
        return LearnerMemoryContext()
    try:
        notes = await store.list_memories(user_id)
    except Exception:  # noqa: BLE001 — a lookup failure must never block open
        logger.warning(
            "learner_memory recall failed for user %s", user_id, exc_info=True
        )
        return LearnerMemoryContext()
    if not notes:
        return LearnerMemoryContext()
    key = normalize_topic_key(topic)
    note = next((n for n in notes if n.get("topic_key") == key), None)
    related = [n for n in notes if n is not note][:_RELATED_LIMIT]
    return LearnerMemoryContext(note=note, related=related)


# --- consolidation ---

_REQUIRED_NOTE_KEYS = ("topic_key", "topic_label", "summary")


def _validate_note_shape(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("note is not a JSON object")
    for key in _REQUIRED_NOTE_KEYS:
        if not str(data.get(key) or "").strip():
            raise ValueError(f"note missing required field: {key}")


def _fallback_note(topic: str, summary: str) -> dict[str, Any]:
    """Deterministic fallback when the generator's JSON is malformed: a
    normalized-topic key and the episode's own (un-merged) summary."""
    key = normalize_topic_key(topic)
    return {
        "topic_key": key,
        "topic_label": topic or key,
        "summary": summary or f"A session on {topic or 'this topic'}.",
        "mastery_estimate": 0.5,
        "recurring_errors": [],
    }


def _format_existing_keys(existing: list[dict[str, Any]]) -> str:
    if not existing:
        return "(none yet — this is the learner's first memory note)"
    return "\n".join(
        f"- {e.get('topic_key')}: {e.get('topic_label')}" for e in existing
    )


def _format_violations(violations: list[str]) -> str:
    if not violations:
        return (
            "(the verifier failed the previous attempt but gave no specific "
            "violations — be conservative: state only what is directly "
            "evidenced in the transcript/summary/assessment above)"
        )
    lines = "\n".join(f"- {v}" for v in violations)
    return f"Fix these specific problems from the previous attempt:\n{lines}"


async def _generate_note(
    llm: LLMProvider, values: dict[str, str]
) -> tuple[dict[str, Any], bool]:
    """Render `consolidate_memory.md` and parse the generator's JSON.
    Returns (note, malformed) — malformed=True on any parse/shape failure."""
    prompt = _render("consolidate_memory.md", values)
    response = await llm.complete([ChatMessage(role="user", content=prompt)])
    try:
        data = _extract_json(response.content)
        _validate_note_shape(data)
        return data, False
    except Exception:  # noqa: BLE001 — malformed JSON triggers the fallback path
        return {}, True


async def _verify_note(
    llm: LLMProvider, values: dict[str, str]
) -> tuple[str, list[str]]:
    """Render `verify_memory.md` and parse the verifier's verdict. A
    malformed verifier response is treated as a conservative "fail" so a bad
    note is never persisted just because the verifier glitched."""
    prompt = _render("verify_memory.md", values)
    response = await llm.complete([ChatMessage(role="user", content=prompt)])
    try:
        data = _extract_json(response.content)
        verdict = str(data.get("verdict") or "fail").strip().lower()
        violations = [str(v) for v in (data.get("violations") or [])]
        if verdict not in ("pass", "fail"):
            verdict = "fail"
        return verdict, violations
    except Exception:  # noqa: BLE001
        return "fail", ["verifier returned no parseable verdict"]


def _episode_values(
    state: SessionState, summary: str, assessment: str, transcript_text: str
) -> dict[str, str]:
    return {
        "topic": state.topic,
        "summary": summary,
        "assessment": assessment,
        "transcript": transcript_text,
    }


def _verify_values(episode: dict[str, str], note: dict[str, Any]) -> dict[str, str]:
    values = dict(episode)
    values["note"] = json.dumps(note, ensure_ascii=False)
    return values


async def _consolidate(
    store: MemoryStoreProtocol,
    generator_llm: LLMProvider,
    verifier_llm: LLMProvider,
    state: SessionState,
    close_record: dict[str, Any],
) -> None:
    transcript_text = "\n".join(
        f"{turn.role}: {turn.content}" for turn in state.transcript
    )
    summary = str(close_record.get("summary") or "")
    assessment = str(close_record.get("assessment") or "")
    episode = _episode_values(state, summary, assessment, transcript_text)

    try:
        existing = await store.list_memories(state.user_id)
    except Exception:  # noqa: BLE001 — keying still works with an empty list
        existing = []

    generate_values = dict(episode)
    generate_values["existing_keys"] = _format_existing_keys(existing)
    generate_values["violations"] = _format_violations([])

    note, malformed = await _generate_note(generator_llm, generate_values)
    if malformed:
        note = _fallback_note(state.topic, summary)

    verdict, violations = await _verify_note(
        verifier_llm, _verify_values(episode, note)
    )

    if verdict != "pass":
        regen_values = dict(episode)
        regen_values["existing_keys"] = _format_existing_keys(existing)
        regen_values["violations"] = _format_violations(violations)
        note2, malformed2 = await _generate_note(verifier_llm, regen_values)
        if malformed2:
            note2 = _fallback_note(state.topic, summary)
        verdict2, _violations2 = await _verify_note(
            verifier_llm, _verify_values(episode, note2)
        )
        if verdict2 != "pass":
            logger.warning(
                "learner_memory: consolidation failed verification twice "
                "(session=%s, topic=%r); skipping write",
                state.session_id,
                state.topic,
            )
            return
        note = note2

    await store.upsert_memory(
        user_id=state.user_id,
        topic_key=str(note.get("topic_key") or normalize_topic_key(state.topic)),
        topic_label=str(note.get("topic_label") or state.topic),
        summary=str(note.get("summary") or summary),
        mastery_estimate=_clamp01(note.get("mastery_estimate")),
        recurring_errors=[str(e) for e in (note.get("recurring_errors") or [])],
        last_session_id=state.session_id,
    )


async def consolidate(
    store: MemoryStoreProtocol,
    generator_llm: LLMProvider,
    verifier_llm: LLMProvider,
    state: SessionState,
    close_record: dict[str, Any],
    enabled: bool,
) -> None:
    """Reflect on a closed episode into the learner's consolidated memory,
    verifying the note is evidenced by the episode before persisting it.

    Non-fatal on ANY failure (log + continue): a close must never be lost to
    a bad reflection."""
    if not enabled:
        return
    try:
        await _consolidate(store, generator_llm, verifier_llm, state, close_record)
    except Exception:  # noqa: BLE001 — see docstring: never lose the close
        logger.warning(
            "learner_memory: consolidate failed for session %s; the close "
            "record itself is unaffected",
            state.session_id,
            exc_info=True,
        )
