"""TutorEngine: orchestrates one tutoring session (PR-E1 contract).

V1 is engine-orchestrated: the engine calls registry tools deterministically
(open → profile.read + content.search; close → store) and feeds results into
prompts. LLM-driven function calling over list_specs() is a later enhancement.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from tutor.llm.interface import ChatMessage, LLMProvider
from tutor.session import policy
from tutor.session.grounding import retrieve_grounding
from tutor.session.markers import parse_task_marker
from tutor.session.models import (
    ContentTraits,
    HelpState,
    SessionState,
    TaskState,
    TechniquePlan,
    Turn,
)
from tutor.session.store import SessionStore
from tutor.session.techniques import select_technique
from tutor.tools.registry import ToolRegistry

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Successful reviews before an item graduates out of the review set (PR-G1).
GRADUATION_REVIEWS = 3


class NoProfileError(RuntimeError):
    """Raised when a session is opened before the questionnaire exists."""


class NoDueReviewError(RuntimeError):
    """Raised when a review session is requested but nothing is due (PR-G1)."""


def _render(template_name: str, values: dict[str, str]) -> str:
    text = (PROMPTS_DIR / template_name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object found in an LLM response."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in LLM response: {text[:200]}")
    result: dict[str, Any] = json.loads(match.group(0))
    return result


def _format_review_memory(items: list[dict[str, Any]]) -> str:
    """Compact memory of prior sessions being revisited (PR-G1)."""
    if not items:
        return "(no prior sessions are due for review)"
    blocks = []
    for i, item in enumerate(items, start=1):
        topic = str(item.get("topic") or "untitled")
        assessment = str(item.get("assessment") or "").strip() or "—"
        next_step = str(item.get("next_step") or "").strip() or "—"
        summary = str(item.get("summary") or "").strip() or "—"
        blocks.append(
            f"[{i}] {topic}\n"
            f"    last assessment: {assessment}\n"
            f"    unfinished next step: {next_step}\n"
            f"    what was covered: {summary}"
        )
    return "\n".join(blocks)


class TutorEngine:
    def __init__(
        self,
        llm: LLMProvider,
        registry: ToolRegistry,
        store: SessionStore,
        user_id: str,
        grounding_enabled: bool = False,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._store = store
        self._user_id = user_id
        self._grounding_enabled = grounding_enabled

    async def open(
        self, topic: str, source_id: str | None = None
    ) -> tuple[SessionState, str]:
        profile = await self._registry.call("profile.read", {})
        if profile is None:
            raise NoProfileError(
                "Complete the questionnaire first: uv run python -m tutor.profile"
            )
        grounding = await retrieve_grounding(
            self._registry,
            topic=topic,
            source_id=source_id,
            enabled=self._grounding_enabled,
        )
        content = grounding.content
        traits = await self._classify(topic, content)
        technique = select_technique(traits, str(profile["self_assessed_level"]))

        state = SessionState(
            session_id="",  # assigned by the store
            user_id=self._user_id,
            topic=topic,
            traits=traits,
            technique=technique,
            source_id=grounding.source_id,
        )
        system = self._system_prompt(state, profile, content)
        response = await self._llm.complete(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(
                    role="user",
                    content=(
                        "Open the session: greet me briefly, state the plan for "
                        "this topic in 2-3 sentences, and give me the first task."
                    ),
                ),
            ]
        )
        raw_opening = response.content
        opening = self._advance_task(state, raw_opening)
        state.transcript.append(Turn(role="tutor", content=raw_opening))
        state.session_id = await self._store.create(state)
        # keep profile/content for the prompt on later turns
        self._profile_cache = profile
        self._content_cache = content
        return state, opening

    async def due_reviews(self) -> list[dict[str, Any]]:
        """This user's sessions due for review (PR-G1)."""
        return await self._store.due_items(self._user_id, datetime.now(timezone.utc))

    async def open_review(self, max_items: int = 3) -> tuple[SessionState, str]:
        """Open a review session over due prior sessions (PR-G1): inject their
        memory, interleave up to `max_items`, run retrieval-first relearning."""
        profile = await self._registry.call("profile.read", {})
        if profile is None:
            raise NoProfileError(
                "Complete the questionnaire first: uv run python -m tutor.profile"
            )
        due = await self.due_reviews()
        if not due:
            raise NoDueReviewError("Nothing is due for review yet.")
        items = due[:max_items]
        memory = _format_review_memory(items)
        labels = ", ".join(str(i.get("topic") or "?") for i in items)
        traits = ContentTraits(
            verifiability="interpretive",
            structure="distributed",
            production="recall",
            source="fallback",
        )
        technique = TechniquePlan(
            primary="retrieval practice",
            feedback_style="contingent, located feedback",
            sequencing="interleaving prior topics",
        )
        state = SessionState(
            session_id="",
            user_id=self._user_id,
            topic=f"Repaso: {labels}",
            traits=traits,
            technique=technique,
            reviewed_ids=[str(i.get("id")) for i in items],
        )
        system = self._system_prompt(state, profile, memory)
        response = await self._llm.complete(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(
                    role="user",
                    content=(
                        "Open the review: greet me briefly, say we are revisiting "
                        "prior material, and start by asking me to recall the first "
                        "item before re-teaching. Open the first task."
                    ),
                ),
            ]
        )
        raw_opening = response.content
        opening = self._advance_task(state, raw_opening)
        state.transcript.append(Turn(role="tutor", content=raw_opening))
        state.session_id = await self._store.create(state)
        self._profile_cache = profile
        self._content_cache = memory
        return state, opening

    async def message(self, session_id: str, text: str) -> tuple[SessionState, str]:
        state = self._state_from_record(await self._store.load(session_id))
        state.help = policy.next_state(state.help, text)
        state.transcript.append(Turn(role="learner", content=text))

        profile = getattr(self, "_profile_cache", None)
        if profile is None:
            profile = await self._registry.call("profile.read", {}) or {}
        content = getattr(self, "_content_cache", None)
        if content is None:
            # Resumed/restarted engine (PR-R1 + M1): re-derive grounding from
            # the anchor persisted on the session so material survives resume.
            grounding = await retrieve_grounding(
                self._registry,
                topic=state.topic,
                source_id=state.source_id,
                enabled=self._grounding_enabled,
            )
            content = grounding.content

        messages = [
            ChatMessage(
                role="system", content=self._system_prompt(state, profile, content)
            )
        ]
        for turn in state.transcript:
            role: Literal["user", "assistant"] = (
                "assistant" if turn.role == "tutor" else "user"
            )
            messages.append(ChatMessage(role=role, content=turn.content))

        response = await self._llm.complete(messages)
        raw_reply = response.content
        reply = self._advance_task(state, raw_reply)
        state.transcript.append(Turn(role="tutor", content=raw_reply))
        await self._store.save_progress(state)
        return state, reply

    async def close(self, session_id: str) -> dict[str, Any]:
        state = self._state_from_record(await self._store.load(session_id))
        transcript_text = "\n".join(
            f"{turn.role}: {turn.content}" for turn in state.transcript
        )
        prompt = _render(
            "close_summary.md",
            {
                "topic": state.topic,
                "technique_primary": state.technique.primary,
                "transcript": transcript_text,
            },
        )
        response = await self._llm.complete([ChatMessage(role="user", content=prompt)])
        data = _extract_json(response.content)
        review_days = int(data.get("review_in_days", 3))
        review_date = datetime.now(timezone.utc) + timedelta(days=review_days)
        await self._store.close(
            session_id,
            summary=str(data.get("summary", "")),
            assessment=str(data.get("assessment", "")),
            next_step=str(data.get("next_step", "")),
            review_date=review_date,
        )
        if state.reviewed_ids:
            await self._store.record_review(
                state.reviewed_ids, review_date, GRADUATION_REVIEWS
            )
        return await self._store.load(session_id)

    async def get(self, session_id: str) -> dict[str, Any]:
        return await self._store.load(session_id)

    async def list_sessions(self, status: str | None = None) -> list[dict[str, Any]]:
        """List this user's sessions (PR-R1); user scoping stays here, same
        as every other engine entry point."""
        return await self._store.list_for_user(self._user_id, status)

    # --- internals ---

    def _advance_task(self, state: SessionState, raw_reply: str) -> str:
        """Parse a task marker (PR-E2): on a new task, bump the task counter
        and reset the per-task help ladder. Returns the learner-facing text
        (marker stripped); the caller stores the raw reply in the transcript."""
        label, cleaned = parse_task_marker(raw_reply)
        if label is not None:
            state.task = TaskState(index=state.task.index + 1, label=label)
            state.help = HelpState()
        return cleaned

    async def _classify(self, topic: str, content: str) -> ContentTraits:
        prompt = _render("classify_traits.md", {"topic": topic, "content": content})
        try:
            response = await self._llm.complete(
                [ChatMessage(role="user", content=prompt)]
            )
            data = _extract_json(response.content)
            return ContentTraits(source="llm", **data)
        except Exception:  # noqa: BLE001 — classification failure must not kill the session
            return ContentTraits(
                verifiability="interpretive",
                structure="distributed",
                production="explain",
                source="fallback",
            )

    def _system_prompt(
        self, state: SessionState, profile: dict[str, Any], content: str
    ) -> str:
        template = "review_system.md" if state.reviewed_ids else "session_system.md"
        return _render(
            template,
            {
                "profile": json.dumps(profile, default=str),
                "topic": state.topic,
                "traits": state.traits.model_dump_json(),
                "technique_primary": state.technique.primary,
                "technique_feedback": state.technique.feedback_style,
                "technique_sequencing": state.technique.sequencing,
                "content": content,
                "help_state": policy.describe(state.help),
                "task_state": (
                    f'current task: #{state.task.index} — "{state.task.label}"'
                    if state.task.index > 0
                    else "no task opened yet — your next message must open one"
                ),
            },
        )

    def _state_from_record(self, record: dict[str, Any]) -> SessionState:
        return SessionState(
            session_id=str(record["id"]),
            user_id=str(record["user_id"]),
            topic=str(record.get("topic") or ""),
            source_id=record.get("source_id"),
            traits=ContentTraits.model_validate(record["traits"]),
            technique=TechniquePlan.model_validate(record["technique"]),
            help=policy.HelpState.model_validate(record.get("help") or {}),
            task=TaskState.model_validate(record.get("task") or {}),
            transcript=[
                Turn.model_validate(t) for t in (record.get("transcript") or [])
            ],
            reviewed_ids=list(record.get("reviewed_ids") or []),
        )
