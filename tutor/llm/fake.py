"""Deterministic in-process LLM provider (PR-DX2).

Selected when ``TUTOR_LLM_PROVIDER=fake``. It imports no esperanto, opens no
network connection and needs no API keys: it inspects the prompts the
:class:`~tutor.session.engine.TutorEngine` sends and returns fixed, schema-valid
responses so the entire tutoring journey can run offline — in the smoke test,
in CI, and on a laptop with zero configuration.

It satisfies the same ``complete()`` interface the engine consumes
(:class:`~tutor.llm.interface.LLMProvider`). The four prompt shapes the engine
emits are told apart by stable substrings of the prompt templates:

* classify  -> a fixed valid content-traits JSON object;
* open      -> an opening turn carrying a ``[[TASK: ...]]`` marker;
* message   -> a deterministic reply (a help-ladder style hint when the learner
               asks for help, a neutral acknowledgement otherwise);
* close     -> a schema-valid closing record JSON object.

The model name is read from the environment but unused — any value is accepted.
"""

from collections.abc import Sequence

from tutor.llm.interface import ChatMessage, ChatResponse, LLMProvider
from tutor.session import policy

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


def _classify_prompt(joined: str) -> bool:
    return "Classify the following study topic" in joined


def _close_prompt(joined: str) -> bool:
    return "Produce its closing record" in joined or "session below is ending" in joined


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
            return _CLOSE_JSON
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
