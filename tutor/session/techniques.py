"""Fixed traits→technique mapping (V1; learned selection is a later version).

Grounding (see PR-E1 contract): retrieval practice for recall; faded worked
examples for novices on apply-type content (worked-example effect) vs
problem-solving with feedback otherwise; Socratic self-explanation for
explain/transfer. Verifiability modulates feedback style; structure modulates
sequencing.
"""

from tutor.session.models import ContentTraits, TechniquePlan

_NOVICE_MARKERS = (
    "beginner",
    "novice",
    "basic",
    "new to",
    "principiante",
    "básico",
    "basico",
    "nuevo",
    "cero",
)


def is_novice(self_assessed_level: str) -> bool:
    """Heuristic over the free-text level from the questionnaire."""
    level = self_assessed_level.lower()
    return any(marker in level for marker in _NOVICE_MARKERS)


def select_technique(traits: ContentTraits, self_assessed_level: str) -> TechniquePlan:
    if traits.production == "recall":
        primary = "retrieval practice"
    elif traits.production == "apply":
        primary = (
            "faded worked examples"
            if is_novice(self_assessed_level)
            else "problem-solving with feedback"
        )
    else:  # explain / transfer
        primary = "socratic self-explanation"

    feedback_style = (
        "immediate corrective feedback"
        if traits.verifiability == "verifiable"
        else "criteria-based discussion"
    )
    sequencing = (
        "prerequisites first"
        if traits.structure == "hierarchical"
        else "interleaving and connections"
    )
    return TechniquePlan(
        primary=primary, feedback_style=feedback_style, sequencing=sequencing
    )
