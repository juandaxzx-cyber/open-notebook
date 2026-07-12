"""Pydantic models for the learner profile (schema mirror of schema.surrealql)."""

import os
from datetime import datetime

from pydantic import BaseModel, Field


def default_user_id() -> str:
    """Current user until real auth exists (AGENTS.md: no global 'the user')."""
    return os.environ.get("TUTOR_USER_ID", "juanda")


class ProfileIn(BaseModel):
    """Questionnaire payload (user_id resolved server-side for now)."""

    learning_goal: str = Field(min_length=1)
    self_assessed_level: str = Field(min_length=1)
    weekly_availability_hours: float = Field(gt=0)
    format_preferences: list[str] = Field(default_factory=list)


class Profile(ProfileIn):
    """Stored profile."""

    user_id: str
    created: datetime | None = None
    updated: datetime | None = None
