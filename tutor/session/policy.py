"""Graduated-help policy (pure; replaces the fixed '2 attempts' rule).

Ladder: 0 none → 1 conceptual hint → 2 procedural hint → 3 partial solution
→ 4 full solution. Full solution is reached by climbing the ladder, or via
explicit give-up after at least one attempt. The engine injects this state
into the prompt every turn, so the constraint is auditable and never depends
on LLM memory alone.
"""

from tutor.session.models import HelpState

_HELP_MARKERS = (
    "hint",
    "help",
    "stuck",
    "pista",
    "ayuda",
    "no sé",
    "no se",
    "atascado",
)
_GIVE_UP_MARKERS = (
    "i give up",
    "give up",
    "me rindo",
    "dime la respuesta",
    "tell me the answer",
    "show me the answer",
    "dame la respuesta",
)


def wants_help(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _HELP_MARKERS)


def gives_up(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _GIVE_UP_MARKERS)


def next_state(state: HelpState, learner_text: str) -> HelpState:
    """Advance the ladder for one learner turn."""
    attempts = state.attempts + 1
    if gives_up(learner_text) and state.attempts >= 1:
        return HelpState(attempts=attempts, help_level=4)
    if wants_help(learner_text) or gives_up(learner_text):
        return HelpState(attempts=attempts, help_level=min(state.help_level + 1, 4))
    return HelpState(attempts=attempts, help_level=state.help_level)


def describe(state: HelpState) -> str:
    """Human/LLM-readable description injected into the system prompt."""
    labels = {
        0: "no help yet — let the learner generate first",
        1: "conceptual hint allowed (point at the relevant idea, no procedure)",
        2: "procedural hint allowed (next step, not the result)",
        3: "partial solution allowed (work part of it together)",
        4: "full solution allowed, with explanation and a follow-up exercise",
    }
    return (
        f"attempts so far: {state.attempts}; "
        f"maximum help allowed now: level {state.help_level} — {labels[state.help_level]}"
    )
