"""Programmatic (no-LLM) transcript metrics (PR-E2).

Computed lexically, so they are immune to LLM-judge biases (verbosity,
self-preference). They complement — never replace — the judged criteria."""

import re

from tutor.session.models import Turn

_PRAISE_TOKENS = (
    "excelente",
    "genial",
    "perfecto",
    "brillante",
    "increíble",
    "fantástico",
    "muy bien",
    "buen trabajo",
    "qué listo",
    "muy agudo",
    "great job",
    "well done",
    "excellent",
    "awesome",
    "amazing",
    "you're smart",
)
_PSEUDO_CHECKS = (
    "¿tiene sentido",
    "tiene sentido?",
    "¿entiendes",
    "entiendes?",
    "¿me sigues",
    "does that make sense",
    "make sense?",
    "got it?",
    "do you understand",
)


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def transcript_metrics(transcript: list[Turn]) -> dict[str, float | int]:
    tutor_turns = [t.content for t in transcript if t.role == "tutor"]
    learner_turns = [t.content for t in transcript if t.role == "learner"]
    tutor_words = sum(_words(t) for t in tutor_turns)
    learner_words = sum(_words(t) for t in learner_turns)
    joined = " ".join(tutor_turns).lower()
    return {
        "tutor_turns": len(tutor_turns),
        "learner_turns": len(learner_turns),
        "tutor_words": tutor_words,
        "learner_words": learner_words,
        "tutor_learner_word_ratio": (
            round(tutor_words / learner_words, 2) if learner_words else float("inf")
        ),
        "avg_tutor_turn_words": (
            round(tutor_words / len(tutor_turns), 1) if tutor_turns else 0
        ),
        "max_tutor_turn_words": max((_words(t) for t in tutor_turns), default=0),
        "praise_tokens": sum(joined.count(tok) for tok in _PRAISE_TOKENS),
        "pseudo_checks": sum(joined.count(tok) for tok in _PSEUDO_CHECKS),
    }


# W1-eval addendum: programmatic (bias-immune) citation-marker check. Only
# the two marker shapes the tutor is ever instructed to use are recognized —
# a generic "anything in brackets" pattern would false-positive on the
# `[[TASK: ...]]` marker (PR-E2), so these are deliberately narrow.
_NUMERIC_CITATION = re.compile(r"\[(\d+)\]")
_SOURCE_CITATION = re.compile(r"\[source:([^\]\s]+)\]")


def _bare_id(source_id: str) -> str:
    """Mirrors `tutor.session.grounding._bare_source_id` (kept local — no
    import from `tutor.session` here, `metrics.py` stays a pure, dependency-
    free leaf module)."""
    return source_id.split(":", 1)[1] if source_id.startswith("source:") else source_id


def invented_citations(
    transcript: list[Turn],
    *,
    grounded: bool,
    whole_source: bool = False,
    source_id: str | None = None,
    max_passages: int | None = None,
) -> int:
    """Count citation-like markers in TUTOR turns that cannot resolve to real
    evidence (W1-eval addendum). No LLM involved — immune to judge bias,
    reported OUTSIDE the 10-criteria means.

    - Ungrounded: nothing was retrieved, so ANY `[n]` or `[source:x]` marker
      is invented.
    - Grounded, whole-source mode: only `[source:<the actual source id>]` is
      valid (that is the citation format `_format_whole_source` instructs);
      any `[n]` marker, or a `[source:x]` for a different id, is invented.
    - Grounded, scoped mode: only `[n]` within `1..max_passages` is valid
      (the format `_format_grounded` instructs); any `[source:x]` marker, or
      an out-of-range `[n]`, is invented. `max_passages=None` (unknown) skips
      the range check — a conservative choice that only undercounts.
    """
    tutor_text = " ".join(t.content for t in transcript if t.role == "tutor")
    numeric = _NUMERIC_CITATION.findall(tutor_text)
    source_marks = _SOURCE_CITATION.findall(tutor_text)

    if not grounded:
        return len(numeric) + len(source_marks)

    invented = 0
    if whole_source:
        bare = _bare_id(source_id) if source_id else None
        invented += len(numeric)
        invented += sum(1 for s in source_marks if s != bare)
    else:
        invented += len(source_marks)
        if max_passages is not None:
            invented += sum(1 for n in numeric if not (1 <= int(n) <= max_passages))
    return invented
