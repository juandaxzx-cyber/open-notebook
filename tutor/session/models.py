"""Session models (PR-E1 contract)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Verifiability = Literal["verifiable", "interpretive"]
Structure = Literal["hierarchical", "distributed"]
Production = Literal["recall", "apply", "explain"]


class ContentTraits(BaseModel):
    """The three content axes (atenea_context.md §3)."""

    verifiability: Verifiability
    structure: Structure
    production: Production
    source: Literal["llm", "fallback"] = "llm"


class TechniquePlan(BaseModel):
    primary: str
    feedback_style: str
    sequencing: str


class HelpState(BaseModel):
    """Graduated-help ladder: 0 none, 1 conceptual hint, 2 procedural hint,
    3 partial solution, 4 full solution."""

    attempts: int = 0
    help_level: Annotated[int, Field(ge=0, le=4)] = 0


class Turn(BaseModel):
    role: Literal["learner", "tutor"]
    content: str


class SessionState(BaseModel):
    session_id: str
    user_id: str
    topic: str
    traits: ContentTraits
    technique: TechniquePlan
    help: HelpState = Field(default_factory=HelpState)
    transcript: list[Turn] = Field(default_factory=list)


# --- API models ---


class SessionOpenRequest(BaseModel):
    topic: str = Field(min_length=1)


class SessionOpenResponse(BaseModel):
    session_id: str
    opening_message: str
    traits: ContentTraits
    technique: TechniquePlan


class MessageRequest(BaseModel):
    text: str = Field(min_length=1)


class MessageResponse(BaseModel):
    reply: str
    attempts: int
    help_level: int


class SessionRecord(BaseModel):
    """Readable session log as stored."""

    session_id: str
    user_id: str
    topic: str | None = None
    traits: ContentTraits | None = None
    technique: TechniquePlan | None = None
    help: HelpState | None = None
    transcript: list[Turn] = Field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    summary: str | None = None
    assessment: str | None = None
    next_step: str | None = None
    review_date: datetime | None = None
