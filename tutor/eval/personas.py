"""Scripted learner personas (PR-E2). Deterministic by design: no LLM plays
the learner, so score changes between runs isolate the tutor prompt (plus
LLM sampling noise), not learner behavior."""

import json
from pathlib import Path

from pydantic import BaseModel, Field

PERSONAS_DIR = Path(__file__).parent / "personas"


class PersonaTurn(BaseModel):
    text: str = Field(min_length=1)
    is_error: bool = False
    note: str = ""  # ground truth for the judge: what is wrong, or the intent


class Persona(BaseModel):
    id: str
    name: str
    topic: str
    profile: dict[str, str]  # canned learner profile fed to the engine
    content: list[str]  # canned "retrieved material" snippets
    turns: list[PersonaTurn] = Field(min_length=1)


def load_personas(directory: Path | None = None) -> list[Persona]:
    directory = directory or PERSONAS_DIR
    personas = [
        Persona.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]
    if not personas:
        raise FileNotFoundError(f"No persona files in {directory}")
    return personas


def annotations_digest(persona: Persona) -> str:
    """Ground-truth block for the judge prompt (reference-anchored judging)."""
    lines = [
        f"Persona: {persona.name}. Learner messages are scripted; numbering "
        f"below refers to learner messages in order (L1 = first learner "
        f"message after the tutor's opening)."
    ]
    for i, turn in enumerate(persona.turns, start=1):
        flag = "CONTAINS ERROR" if turn.is_error else "no error"
        note = f" — {turn.note}" if turn.note else ""
        lines.append(f"L{i}: {flag}{note}")
    return "\n".join(lines)
