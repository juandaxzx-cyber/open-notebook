"""profile.read / profile.write — the learner profile as tutor tools."""

from typing import Any

from pydantic import BaseModel

from tutor.profile.models import ProfileIn, default_user_id
from tutor.profile.service import ProfileService
from tutor.tools.registry import ToolSpec


class EmptyInput(BaseModel):
    pass


class ProfileReadInput(BaseModel):
    # PR-BT1: optional and additive — absent/None keeps the pre-BT1 behavior
    # (default_user_id(), the TUTOR_USER_ID env tenant) byte-identical for
    # every existing caller that still invokes this tool with `{}`. The
    # engine is the only caller that ever sets this, with the per-request
    # resolved identity (never LLM/user-controlled — this tool is called
    # deterministically by the engine, not via LLM function calling in V1).
    user_id: str | None = None


def profile_read_tool(service: ProfileService) -> ToolSpec:
    async def handler(args: ProfileReadInput) -> dict[str, Any] | None:
        profile = await service.get_profile(args.user_id or default_user_id())
        return profile.model_dump(mode="json") if profile else None

    return ToolSpec(
        name="profile.read",
        description=(
            "Read the learner's persistent profile: goal, self-assessed level, "
            "weekly availability and format preferences. Returns null if the "
            "initial questionnaire hasn't been completed yet."
        ),
        input_model=ProfileReadInput,
        handler=handler,
    )


def profile_write_tool(service: ProfileService) -> ToolSpec:
    async def handler(args: ProfileIn) -> dict[str, Any]:
        stored = await service.upsert_profile(default_user_id(), args)
        return stored.model_dump(mode="json")

    return ToolSpec(
        name="profile.write",
        description=(
            "Create or update the learner's profile (goal, level, weekly "
            "availability, format preferences). Use when the learner states a "
            "new goal or their situation changes."
        ),
        input_model=ProfileIn,
        handler=handler,
    )
