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
