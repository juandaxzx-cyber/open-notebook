"""TutorEngine: orchestrates one tutoring session (PR-E1 contract).

V1 is engine-orchestrated: the engine calls registry tools deterministically
(open → profile.read + content.search; close → store) and feeds results into
prompts. LLM-driven function calling over list_specs() is a later enhancement.
"""

import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from tutor.llm.interface import ChatMessage, LLMProvider
from tutor.session import policy, verification
from tutor.session.grounding import DEFAULT_BUDGET_TOKENS, retrieve_grounding
from tutor.session.markers import parse_task_marker
from tutor.session.memory import LearnerMemoryContext, consolidate, recall
from tutor.session.models import (
    ContentTraits,
    HelpState,
    SessionState,
    TaskState,
    TechniquePlan,
    Turn,
)
from tutor.session.scheduling import DEFAULT_HORIZON_DAYS, parse_quality
from tutor.session.store import SessionStore
from tutor.session.techniques import select_technique
from tutor.tools.registry import ToolRegistry

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class NoProfileError(RuntimeError):
    """Raised when a session is opened before the questionnaire exists."""


class NoDueReviewError(RuntimeError):
    """Raised when a review session is requested but nothing is due (PR-G1)."""


def _render(template_name: str, values: dict[str, str]) -> str:
    text = (PROMPTS_DIR / template_name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    # Normalize to exactly one trailing newline: every template already
    # follows this convention, and it is what keeps the disabled-memory path
    # byte-identical to pre-G2 output when {{memory_section}} renders empty
    # (PR-G2 backward-compat lock) instead of leaving a stray blank line.
    return text.rstrip("\n") + "\n"


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object found in an LLM response."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in LLM response: {text[:200]}")
    result: dict[str, Any] = json.loads(match.group(0))
    return result


def _closed_world_section(content: str) -> str:
    """PR-W1: closed-world + mandatory-citations section, injected only for
    GROUNDED sessions (same "GROUNDED SOURCE" detection the template's own
    static instruction already uses). "" for ungrounded sessions — combined
    with the `{{closed_world_section}}` placeholder sitting inline (not on
    its own line) in session_system.md, this keeps ungrounded/no-grounding
    prompts byte-identical to pre-W1 output (backward-compat lock, M1-style).
    """
    if not content.startswith("GROUNDED SOURCE"):
        return ""
    return (
        "\n\n## Closed-world contract (grounded session)\n"
        "Teach ONLY from the GROUNDED SOURCE above, or say explicitly that "
        "something is outside it — never state a fact as settled when the "
        "source does not cover it. Cite every factual claim: use the exact "
        "[n] passage marker (or [source:id] in whole-source mode) given "
        "above, right next to the claim it supports. Never invent a marker "
        "or record id, and never attach a citation to a claim the cited "
        "passage does not actually support — a wrong citation is the single "
        "worst mistake you can make here."
    )


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
        memory_enabled: bool = False,
        verifier_llm: LLMProvider | None = None,
        review_horizon_days: float = DEFAULT_HORIZON_DAYS,
        verify_turns: str = "off",
        verify_profile: str = "high",
        grounding_budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._store = store
        self._user_id = user_id
        self._grounding_enabled = grounding_enabled
        self._memory_enabled = memory_enabled
        # Unset verifier ⇒ falls back to the tutor's own LLM (PR-G2 contract:
        # zero-key smoke keeps working); app.py resolves + warns on same-family
        # from config, this is just a safe default for direct construction.
        self._verifier_llm = verifier_llm or llm
        # SM-2 forgetting horizon (PR-G3): TUTOR_REVIEW_HORIZON_DAYS, resolved
        # by app.py from settings; a safe default for direct construction.
        self._review_horizon_days = review_horizon_days
        # PR-W1: per-turn verification scope/profile default to "off"/"high"
        # here (safe for direct/test construction, same pattern as
        # grounding_enabled/memory_enabled above) — app.py wires the
        # config's "grounded"/"high" defaults through for the real service.
        self._verify_turns = verify_turns
        self._verify_profile = verify_profile
        self._grounding_budget_tokens = grounding_budget_tokens

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
            budget_tokens=self._grounding_budget_tokens,
        )
        content = grounding.content
        traits = await self._classify(topic, content)
        technique = select_technique(traits, str(profile["self_assessed_level"]))
        memory = await recall(self._store, self._user_id, topic, self._memory_enabled)

        state = SessionState(
            session_id="",  # assigned by the store
            user_id=self._user_id,
            topic=topic,
            traits=traits,
            technique=technique,
            source_id=grounding.source_id,
        )
        system = self._system_prompt(state, profile, content, memory)
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(
                role="user",
                content=(
                    "Open the session: greet me briefly, state the plan for "
                    "this topic in 2-3 sentences, and give me the first task."
                ),
            ),
        ]
        raw_opening, trace = await self._complete_verified(
            messages, evidence=content, grounded=grounding.grounded
        )
        opening = self._advance_task(state, raw_opening)
        state.transcript.append(
            Turn(role="tutor", content=raw_opening, verification=trace)
        )
        state.last_verification_outcome = trace["outcome"] if trace else None
        state.session_id = await self._store.create(state)
        # keep profile/content/memory for the prompt on later turns
        self._profile_cache = profile
        self._content_cache = content
        self._memory_cache = memory
        self._grounded_cache = grounding.grounded
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
        review_memory_text = _format_review_memory(items)
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
        learner_memory = await recall(
            self._store, self._user_id, state.topic, self._memory_enabled
        )
        system = self._system_prompt(state, profile, review_memory_text, learner_memory)
        messages = [
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
        # Review sessions are out of PR-M grounding scope (no `source_id`,
        # no `retrieve_grounding` call) — W1 treats them as ungrounded:
        # verified only under `TUTOR_VERIFY_TURNS=all`, with the
        # abstention-only check (smallest-reading decision, see PR report).
        raw_opening, trace = await self._complete_verified(
            messages, evidence=review_memory_text, grounded=False
        )
        opening = self._advance_task(state, raw_opening)
        state.transcript.append(
            Turn(role="tutor", content=raw_opening, verification=trace)
        )
        state.last_verification_outcome = trace["outcome"] if trace else None
        state.session_id = await self._store.create(state)
        self._profile_cache = profile
        self._content_cache = review_memory_text
        self._memory_cache = learner_memory
        self._grounded_cache = False
        return state, opening

    async def message(self, session_id: str, text: str) -> tuple[SessionState, str]:
        state = self._state_from_record(await self._store.load(session_id))
        state.help = policy.next_state(state.help, text)
        state.transcript.append(Turn(role="learner", content=text))

        profile = getattr(self, "_profile_cache", None)
        if profile is None:
            profile = await self._registry.call("profile.read", {}) or {}
        content = getattr(self, "_content_cache", None)
        grounded = getattr(self, "_grounded_cache", False)
        if content is None:
            # Resumed/restarted engine (PR-R1 + M1): re-derive grounding from
            # the anchor persisted on the session so material survives resume.
            grounding = await retrieve_grounding(
                self._registry,
                topic=state.topic,
                source_id=state.source_id,
                enabled=self._grounding_enabled,
                budget_tokens=self._grounding_budget_tokens,
            )
            content = grounding.content
            grounded = grounding.grounded
        # Memory is recalled once, at open/open_review (PR-G2 contract); a
        # resumed engine with no cache simply carries no memory section here
        # rather than issuing a second recall call from this seam.
        memory = getattr(self, "_memory_cache", None) or LearnerMemoryContext()

        messages = [
            ChatMessage(
                role="system",
                content=self._system_prompt(state, profile, content, memory),
            )
        ]
        for turn in state.transcript:
            role: Literal["user", "assistant"] = (
                "assistant" if turn.role == "tutor" else "user"
            )
            messages.append(ChatMessage(role=role, content=turn.content))

        raw_reply, trace = await self._complete_verified(
            messages, evidence=content, grounded=grounded
        )
        reply = self._advance_task(state, raw_reply)
        state.transcript.append(
            Turn(role="tutor", content=raw_reply, verification=trace)
        )
        state.last_verification_outcome = trace["outcome"] if trace else None
        await self._store.save_progress(state)
        return state, reply

    async def close(self, session_id: str) -> dict[str, Any]:
        state = self._state_from_record(await self._store.load(session_id))
        transcript_text = "\n".join(
            f"{turn.role}: {turn.content}" for turn in state.transcript
        )
        # PR-G3: review sessions ask the close JSON for a per-reviewed-item
        # quality grade (0-5, SM-2 style), aligned positionally with
        # `state.reviewed_ids` — the LLM never sees internal session ids, it
        # just grades the items in the order they were covered. Both extra
        # template values are "" for a normal (non-review) close, keeping
        # its schema unchanged from pre-G3.
        review_grades_instructions = ""
        review_grades_field = ""
        if state.reviewed_ids:
            n = len(state.reviewed_ids)
            review_grades_instructions = (
                f"- This is a REVIEW session revisiting {n} prior item(s), in "
                "the order they were covered in the transcript above. For "
                "EACH of them, in that same order, grade the learner's "
                "recall quality this session on a 0-5 scale (SM-2 style): "
                "0-2 = failed to recall / needed the answer given to them; "
                "3 = recalled with noticeable effort or a partial error; "
                "4 = recalled correctly with some hesitation; 5 = recalled "
                "quickly and correctly. Base every grade strictly on the "
                "transcript.\n"
            )
            review_grades_field = (
                ',\n  "review_grades": [<int 0-5 per item, same order as above>]'
            )
        prompt = _render(
            "close_summary.md",
            {
                "topic": state.topic,
                "technique_primary": state.technique.primary,
                "transcript": transcript_text,
                "review_grades_instructions": review_grades_instructions,
                "review_grades_field": review_grades_field,
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
            raw_grades = data.get("review_grades")
            raw_list = raw_grades if isinstance(raw_grades, list) else []
            # Absent sid in `grades` = malformed/missing grade: the store
            # schedules it with a neutral q=3 but never evicts (contract).
            parsed = {
                sid: parse_quality(raw_list[i] if i < len(raw_list) else None)
                for i, sid in enumerate(state.reviewed_ids)
            }
            grades = {sid: q for sid, q in parsed.items() if q is not None}
            await self._store.record_review(
                state.reviewed_ids,
                grades,
                datetime.now(timezone.utc),
                self._review_horizon_days,
            )
        record = await self._store.load(session_id)
        await consolidate(
            self._store,
            self._llm,
            self._verifier_llm,
            state,
            record,
            self._memory_enabled,
        )
        return record

    async def get(self, session_id: str) -> dict[str, Any]:
        return await self._store.load(session_id)

    async def list_sessions(self, status: str | None = None) -> list[dict[str, Any]]:
        """List this user's sessions (PR-R1); user scoping stays here, same
        as every other engine entry point."""
        return await self._store.list_for_user(self._user_id, status)

    async def list_memories(self) -> list[dict[str, Any]]:
        """This user's consolidated memory notes, recency-ordered (PR-G2);
        user scoping stays here, same as every other engine entry point."""
        return await self._store.list_memories(self._user_id)

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

    async def _complete_verified(
        self,
        messages: list[ChatMessage],
        *,
        evidence: str,
        grounded: bool,
    ) -> tuple[str, dict[str, Any] | None]:
        """THE integration point (PR-W1): every outgoing tutor reply is
        produced through this one method (called from `open`, `open_review`
        and `message`). Removing the `verification.escalate(...)` call below
        reverts the feature to a plain, unverified `self._llm.complete(...)`.

        Returns (text-to-ship, persisted-trace-or-None). The trace is None
        when the turn was never gated (`TUTOR_VERIFY_TURNS=off`, or an
        ungrounded turn under the default "grounded" scope) — that is also
        exactly the condition under which `text-to-ship` is the raw,
        unmodified `self._llm.complete(...)` output (byte-identical lock).
        """
        response = await self._llm.complete(messages)
        raw_reply = response.content
        if not verification.applies(self._verify_turns, grounded):
            return raw_reply, None
        result = await verification.escalate(
            generator_llm=self._llm,
            verifier_llm=self._verifier_llm,
            messages=messages,
            reply=raw_reply,
            evidence=evidence,
            grounded=grounded,
            profile=self._verify_profile,
        )
        trace = asdict(result.trace) if result.trace else None
        return result.text, trace

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
        self,
        state: SessionState,
        profile: dict[str, Any],
        content: str,
        memory: LearnerMemoryContext | None = None,
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
                # PR-G2: "" when disabled/no note — keeps the prompt
                # byte-identical to pre-G2 output (backward-compat lock).
                "memory_section": (memory or LearnerMemoryContext()).content,
                # PR-W1: "" for ungrounded content — keeps the prompt
                # byte-identical to pre-W1 output for ungrounded sessions
                # (backward-compat lock, M1-style). review_system.md has no
                # `{{closed_world_section}}` placeholder, so this key is
                # simply unused there (`_render`'s replace is a no-op).
                "closed_world_section": _closed_world_section(content),
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
