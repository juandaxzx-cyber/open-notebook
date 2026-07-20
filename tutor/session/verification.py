"""Per-turn verification of tutor replies (PR-W1) — generalizes G2's fenced
consolidation-note verification (`tutor/session/memory.py`) to the live
tutoring turn: the learner-facing gap identified in
`docs/atenea/hallucination_verification_sota.md` §4.

One seam, two entry points:

* `verify_turn` — a single verifier call against one reply: grounded sessions
  get a RAGAS-faithfulness-shaped claim check plus a citation check (mis-
  citation is flagged explicitly — the education field's worst failure);
  ungrounded sessions get no pretend-verification, only the abstention /
  overclaiming / fabricated-reference check (§5 of the SOTA note).
* `escalate` — the full ladder for one reply: verify -> retry -> escalate ->
  ship. The engine calls this exactly once per outgoing reply, at one
  integration point (`TutorEngine._complete_verified`); removing that call
  reverts the feature to plain, unverified replies.

Cost control is scope (`TUTOR_VERIFY_TURNS`) and profile
(`TUTOR_VERIFY_PROFILE`) ONLY (developer decision 2026-07-19: no skip
heuristic — every reply within scope is verified, a failed verification is
signal to collect, not a cost to avoid).

**High profile** (default): verify -> fail -> the generator retries once
(violations injected as constraints) -> re-verify -> fail -> escalate to the
verifier acting as generator, up to 2 attempts, each re-verified -> all fail
-> ship the last attempt as the best-available answer (outcome
"limits-admitted"). The retry/escalation instruction itself tells the model
to honestly admit the session's knowledge limits when it cannot satisfy the
constraints, rather than keep guessing — so no extra call is needed to
produce that admission; it is baked into every regeneration attempt. Worst
case: 3 regenerations + 4 verifier calls, matching the contract's budget.

**Cheap profile**: verify -> fail -> the generator retries once -> still fail
-> ship flagged (outcome "flagged"), no escalation. Worst case: 1
regeneration + 2 verifier calls.

**Malformed verifier JSON**, at ANY step, in EITHER profile, is NOT treated
as a fail — that is G2's convention for memory writes, where skipping a
write is safe. A live tutoring turn must never be lost to an instrument
failure: the CURRENT reply ships unflagged (outcome "clean"), logged.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from tutor.llm.interface import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

Verdict = Literal["pass", "fail"]
Outcome = Literal["clean", "corrected", "escalated", "limits-admitted", "flagged"]

# High profile: up to 2 verifier-as-generator attempts after the gen-retry.
_MAX_ESCALATIONS = 2


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


@dataclass
class TurnVerdict:
    """One verifier call's result. `malformed=True` means the verifier's own
    output could not be parsed — per contract this is NOT a fail (unlike
    G2's memory-write verification): the caller ships the current reply
    unflagged rather than blocking a live turn on an instrument failure."""

    verdict: Verdict
    violations: list[str] = field(default_factory=list)
    malformed: bool = False


@dataclass
class AttemptRecord:
    """One rung of the ladder, kept for the persisted trace."""

    attempt: int
    generator: Literal["primary", "escalated"]
    verdict: Verdict
    violations: list[str] = field(default_factory=list)
    malformed: bool = False


@dataclass
class VerificationTrace:
    """The full persisted record of one gated turn (contract: "verdicts,
    violations per attempt, escalations, outcome")."""

    outcome: Outcome
    profile: str
    attempts: list[AttemptRecord] = field(default_factory=list)


@dataclass
class VerifiedReply:
    text: str
    trace: VerificationTrace | None  # None when out of scope (never gated)


def applies(scope: str, grounded: bool) -> bool:
    """Whether a reply in this scope/groundedness should be gated at all.
    The ONLY cost-control lever besides profile (contract: no skip
    heuristic) — every reply that `applies()` returns True for is verified,
    full stop, regardless of its content (no "is this claim-bearing?"
    classifier)."""
    if scope == "off":
        return False
    if scope == "all":
        return True
    return grounded  # "grounded" (default): ungrounded turns are skipped


_GROUNDED_INSTRUCTIONS = (
    "This is a GROUNDED session: the tutor was given retrieved material "
    "(below) and told to teach from it and cite it — [n] markers in scoped "
    "mode, or [source:id] in whole-source mode. Check TWO things:\n"
    "1. Faithfulness: every factual claim the reply states as settled fact "
    "must be directly supported by the evidence below, or explicitly marked "
    "by the tutor as outside what the material covers. Flag any claim the "
    "evidence does not support.\n"
    "2. Citations: every [n] / [source:id] marker in the reply must point "
    "to a passage that actually supports the claim next to it. A citation "
    "attached to a claim the cited passage does NOT support is a "
    "mis-citation — flag it explicitly, quoting the claim and the marker "
    "(this is the worst failure mode: learners follow these citations).\n"
    "Do not flag pedagogical moves (questions, hints, encouragement, "
    "restating the learner's words, task-setting) — verify only claims "
    "presented as established fact."
)

_UNGROUNDED_INSTRUCTIONS = (
    "This is an UNGROUNDED session: no retrieved material was given to the "
    "tutor, so there is nothing to check factual claims against. Do NOT "
    "invent a standard to check claims by. Check ONLY:\n"
    "1. Overclaiming: does the reply assert specific facts with unwarranted "
    "confidence a tutor without a source could not actually know for "
    "certain (precise numbers, dates, named studies, quotes) as settled "
    "fact?\n"
    "2. Fabricated references: any citation-like marker ([n], [source:id], "
    "a book/paper/URL) is disallowed here — there is no material to cite. "
    "Flag any if present.\n"
    "3. Abstention: when genuinely uncertain, does the reply say so "
    "plainly, or does it guess?\n"
    "Do not flag ordinary teaching content, examples, or reasoning that "
    "carries no claim of unverifiable fact."
)


async def verify_turn(
    verifier_llm: LLMProvider,
    reply: str,
    evidence: str,
    *,
    grounded: bool,
) -> TurnVerdict:
    """One verifier call against a single tutor reply."""
    prompt = _render(
        "verify_turn.md",
        {
            "mode_label": " (grounded)" if grounded else " (ungrounded)",
            "mode_instructions": (
                _GROUNDED_INSTRUCTIONS if grounded else _UNGROUNDED_INSTRUCTIONS
            ),
            "reply": reply,
            "evidence": (
                evidence
                if grounded
                else "(none — this is an ungrounded session; no material was retrieved)"
            ),
        },
    )
    response = await verifier_llm.complete([ChatMessage(role="user", content=prompt)])
    try:
        data = _extract_json(response.content)
        verdict = str(data.get("verdict") or "").strip().lower()
        violations = [str(v) for v in (data.get("violations") or [])]
        if verdict not in ("pass", "fail"):
            raise ValueError(f"unexpected verdict: {verdict!r}")
        return TurnVerdict(verdict=verdict, violations=violations)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — malformed verifier output is NOT a fail here
        logger.warning(
            "verify_turn: verifier returned no parseable verdict; shipping "
            "the current reply unflagged (an instrument failure must never "
            "lose a live tutoring turn)",
            exc_info=True,
        )
        return TurnVerdict(verdict="pass", violations=[], malformed=True)


_RETRY_INSTRUCTION = (
    "A verifier checked your reply above against the session's evidence and "
    "rejected it for the reason(s) below. Revise your reply to the learner: "
    "keep the same turn structure, task/task-marker behavior and tone, but "
    "fix every listed problem. Ground every factual claim strictly in the "
    "retrieved material (or state plainly it is outside what the material "
    "covers); fix or remove every mis-citation. If you genuinely cannot "
    "satisfy the constraints within what the material supports, say so "
    "honestly to the learner instead of guessing — an honest 'this isn't in "
    "what we have here; here's my best understanding' is a valid, complete "
    "reply.\n\n{violations}"
)


def _format_violations(violations: list[str]) -> str:
    if not violations:
        return (
            "(the verifier failed this attempt but gave no specific "
            "violations — be conservative: keep only claims directly "
            "evidenced above, and drop or hedge anything you cannot "
            "support.)"
        )
    lines = "\n".join(f"- {v}" for v in violations)
    return f"Specific problems to fix:\n{lines}"


def _retry_messages(
    messages: Sequence[ChatMessage], previous_reply: str, violations: list[str]
) -> list[ChatMessage]:
    return [
        *messages,
        ChatMessage(role="assistant", content=previous_reply),
        ChatMessage(
            role="user",
            content=_RETRY_INSTRUCTION.format(
                violations=_format_violations(violations)
            ),
        ),
    ]


async def _regenerate(
    llm: LLMProvider,
    messages: Sequence[ChatMessage],
    previous_reply: str,
    violations: list[str],
) -> str:
    response = await llm.complete(_retry_messages(messages, previous_reply, violations))
    return response.content


async def escalate(
    *,
    generator_llm: LLMProvider,
    verifier_llm: LLMProvider,
    messages: Sequence[ChatMessage],
    reply: str,
    evidence: str,
    grounded: bool,
    profile: str,
) -> VerifiedReply:
    """Run the full verify -> retry -> escalate ladder for one reply.

    `messages` is the EXACT message list that produced `reply` (system +
    conversation so far, without `reply` itself appended) — regeneration
    replays it with the previous reply and a correction instruction appended,
    so the model sees exactly what it said and why it was rejected.
    """
    attempts: list[AttemptRecord] = []
    current = reply

    verdict = await verify_turn(verifier_llm, current, evidence, grounded=grounded)
    attempts.append(
        AttemptRecord(
            1, "primary", verdict.verdict, verdict.violations, verdict.malformed
        )
    )
    if verdict.malformed:
        return VerifiedReply(current, VerificationTrace("clean", profile, attempts))
    if verdict.verdict == "pass":
        return VerifiedReply(current, VerificationTrace("clean", profile, attempts))

    # Attempt 2: the generator retries once, violations injected as constraints.
    current = await _regenerate(generator_llm, messages, current, verdict.violations)
    verdict = await verify_turn(verifier_llm, current, evidence, grounded=grounded)
    attempts.append(
        AttemptRecord(
            2, "primary", verdict.verdict, verdict.violations, verdict.malformed
        )
    )
    if verdict.malformed:
        return VerifiedReply(current, VerificationTrace("clean", profile, attempts))
    if verdict.verdict == "pass":
        return VerifiedReply(current, VerificationTrace("corrected", profile, attempts))

    if profile == "cheap":
        return VerifiedReply(current, VerificationTrace("flagged", profile, attempts))

    # High profile: escalate to the verifier acting as generator, <=2 attempts.
    for i in range(_MAX_ESCALATIONS):
        current = await _regenerate(verifier_llm, messages, current, verdict.violations)
        verdict = await verify_turn(verifier_llm, current, evidence, grounded=grounded)
        attempts.append(
            AttemptRecord(
                3 + i,
                "escalated",
                verdict.verdict,
                verdict.violations,
                verdict.malformed,
            )
        )
        if verdict.malformed:
            return VerifiedReply(current, VerificationTrace("clean", profile, attempts))
        if verdict.verdict == "pass":
            return VerifiedReply(
                current, VerificationTrace("escalated", profile, attempts)
            )

    return VerifiedReply(
        current, VerificationTrace("limits-admitted", profile, attempts)
    )
