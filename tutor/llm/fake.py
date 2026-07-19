"""Deterministic in-process LLM provider (PR-DX2, extended PR-G2).

Selected when ``TUTOR_LLM_PROVIDER=fake``. It imports no esperanto, opens no
network connection and needs no API keys: it inspects the prompts the
:class:`~tutor.session.engine.TutorEngine` sends and returns fixed, schema-valid
responses so the entire tutoring journey can run offline — in the smoke test,
in CI, and on a laptop with zero configuration.

It satisfies the same ``complete()`` interface the engine consumes
(:class:`~tutor.llm.interface.LLMProvider`). The prompt shapes the engine
emits are told apart by stable substrings of the prompt templates:

* classify    -> a fixed valid content-traits JSON object;
* open        -> an opening turn carrying a ``[[TASK: ...]]`` marker;
* message     -> a deterministic reply (a help-ladder style hint when the
                 learner asks for help, a neutral acknowledgement otherwise);
* close       -> a schema-valid closing record JSON object; a REVIEW
                 session's close additionally carries deterministic
                 per-item `review_grades` (PR-G3);
* consolidate -> a schema-valid learner-memory note (PR-G2), keyed off the
                 same normalized-topic slug `recall` looks up so a fresh
                 session on the same topic finds it;
* verify      -> a "pass" verdict (PR-G2) — the deterministic default never
                 blocks a write; `FakeVerifierProvider` below is the fixture
                 tests use to exercise the fail paths.

The model name is read from the environment but unused — any value is accepted.
"""

import json
import re
from collections.abc import Sequence

from tutor.llm.interface import ChatMessage, ChatResponse, LLMProvider
from tutor.session import policy
from tutor.session.memory import normalize_topic_key

# A fixed, valid ContentTraits payload (matches classify_traits.md's schema).
_TRAITS_JSON = (
    '{"verifiability": "verifiable", "structure": "hierarchical", '
    '"production": "apply"}'
)

# A schema-valid closing record (matches close_summary.md's schema). Phrasing is
# generic and grounded in "a short session" so it is honest for any transcript.
_CLOSE_JSON = (
    '{"summary": "A short introductory session: the topic was opened, one task '
    'was set and the learner made a first attempt with some guided help.", '
    '"assessment": "Too early to assess mastery from a single exchange; the '
    'learner engaged but has not yet demonstrated independent application.", '
    '"next_step": "Resume with one more worked example, then a similar problem '
    'to solve unaided.", "review_in_days": 3}'
)

# Same closing record, extended with deterministic per-item quality grades
# (PR-G3) for a REVIEW session's close. A fixed-length list of moderate-good
# grades (4/5) is safe regardless of how many items were actually reviewed —
# the engine only reads as many entries as `reviewed_ids` has and defaults
# any it can't find, so a longer list never causes an index error.
_CLOSE_JSON_REVIEW = (
    '{"summary": "A short review session: prior items were revisited with '
    'retrieval-first practice and some contingent hints.", '
    '"assessment": "Recall was mostly successful with occasional effort; no '
    'item required the full answer to be given.", '
    '"next_step": "Keep revisiting the weaker item(s) at the next scheduled '
    'review.", "review_in_days": 3, "review_grades": [4, 4, 4, 4, 4]}'
)

# The opening turn always declares the first task via a marker so the engine's
# task counter advances to 1 (the marker is stripped from the learner-facing text).
_OPENING = (
    "[[TASK: activate prior knowledge]]\n"
    "Hi! Here is the plan: we will build this topic up from what you already "
    "know, one small step at a time, and check each step before moving on. "
    "First task: tell me, in your own words, what you already know about this."
)

# A help-ladder style reply: a located hint that points at the idea without
# handing over the procedure or the answer (help level 1-2 territory).
_HELP_REPLY = (
    "Good that you flagged it. Here is a hint, not the answer: look again at the "
    "definition you would use first, and check which single quantity it asks you "
    "to compute before anything else. What does that first quantity turn out to be?"
)

# A neutral acknowledgement for a plain attempt: keeps the learner generating.
_MESSAGE_REPLY = (
    "Thanks — I can see your attempt. Walk me through how you got there, step by "
    "step, so we can check the reasoning together before I say anything."
)

# A pass verdict (matches verify_memory.md's schema) — the deterministic
# default so consolidation never blocks on verification in the smoke path.
_VERIFY_PASS_JSON = '{"verdict": "pass", "violations": []}'

# A fail verdict with one plausible violation, for the fail-then-pass /
# double-fail test fixtures below.
_VERIFY_FAIL_JSON = (
    '{"verdict": "fail", "violations": ["claims mastery the transcript does '
    'not show the learner demonstrating"]}'
)


def _classify_prompt(joined: str) -> bool:
    return "Classify the following study topic" in joined


def _close_prompt(joined: str) -> bool:
    return "Produce its closing record" in joined or "session below is ending" in joined


def _review_close_prompt(joined: str) -> bool:
    """A close prompt for a REVIEW session carries the `"review_grades"`
    schema field literal injected by `engine.close` (PR-G3) — that marker is
    only present when `state.reviewed_ids` was non-empty."""
    return '"review_grades"' in joined


def _consolidate_prompt(joined: str) -> bool:
    return "Reflect on this tutoring episode" in joined


def _verify_prompt(joined: str) -> bool:
    return "Verify this consolidated learner-memory note" in joined


def _topic_from_prompt(joined: str) -> str:
    match = re.search(r"^TOPIC: (.*)$", joined, re.MULTILINE)
    return match.group(1).strip() if match else "general"


def _consolidate_json(joined: str) -> str:
    """A deterministic, schema-valid consolidation note (matches
    `consolidate_memory.md`'s schema). `topic_key` is the same normalized
    slug `tutor.session.memory.recall` looks up, so a second session on the
    same topic finds this note (PR-DX2/G2 smoke: "second open succeeds")."""
    topic = _topic_from_prompt(joined)
    payload = {
        "topic_key": normalize_topic_key(topic),
        "topic_label": topic,
        "summary": (
            "The learner engaged with this topic in a guided session and made "
            "a first attempt with some support; independent mastery is not yet "
            "demonstrated."
        ),
        "mastery_estimate": 0.4,
        "recurring_errors": [],
    }
    return json.dumps(payload)


class FakeProvider(LLMProvider):
    """Deterministic, offline stand-in for a real LLM provider."""

    def __init__(self, model_name: str = "fake") -> None:
        self._model = model_name or "fake"

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        return ChatResponse(
            content=self._reply(list(messages)),
            provider="fake",
            model=self._model,
        )

    def _reply(self, messages: list[ChatMessage]) -> str:
        joined = "\n".join(m.content for m in messages)
        if _classify_prompt(joined):
            return _TRAITS_JSON
        if _close_prompt(joined):
            return _CLOSE_JSON_REVIEW if _review_close_prompt(joined) else _CLOSE_JSON
        if _consolidate_prompt(joined):
            return _consolidate_json(joined)
        if _verify_prompt(joined):
            return _VERIFY_PASS_JSON
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        if last_user.startswith("Open the session") or last_user.startswith(
            "Open the review"
        ):
            return _OPENING
        if policy.wants_help(last_user) or policy.gives_up(last_user):
            return _HELP_REPLY
        return _MESSAGE_REPLY


class FakeVerifierProvider(LLMProvider):
    """Deterministic PR-G2 test fixture: fails the first `fail_times`
    verifications it sees, then passes. Also answers a `consolidate_memory.md`
    regeneration prompt like a generator would, since a failed verification
    hands generation to the verifier (see `tutor.session.memory.consolidate`).

    `fail_times=1` -> fail-then-pass (the write succeeds on the regenerated
    note). `fail_times=2` -> double-fail (both verifications fail, so the
    write is skipped and the close record stays intact)."""

    def __init__(self, model_name: str = "fake-verifier", fail_times: int = 1) -> None:
        self._model = model_name or "fake-verifier"
        self._fail_times = fail_times
        self._verify_calls = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        joined = "\n".join(m.content for m in messages)
        if _consolidate_prompt(joined):
            return ChatResponse(
                content=_consolidate_json(joined), provider="fake", model=self._model
            )
        if _verify_prompt(joined):
            self._verify_calls += 1
            content = (
                _VERIFY_FAIL_JSON
                if self._verify_calls <= self._fail_times
                else _VERIFY_PASS_JSON
            )
            return ChatResponse(content=content, provider="fake", model=self._model)
        return ChatResponse(content=_MESSAGE_REPLY, provider="fake", model=self._model)
