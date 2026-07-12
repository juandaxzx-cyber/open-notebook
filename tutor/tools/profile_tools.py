"""profile.read / profile.write — the learner profile as tutor tools."""

from typing import Any

from pydantic import BaseModel

from tutor.profile.models import ProfileIn, default_user_id
from tutor.profile.service import ProfileService
from tutor.tools.registry import ToolSpec


class EmptyInput(BaseModel):
    pass


def profile_read_tool(service: ProfileService) -> ToolSpec:
    async def handler(args: EmptyInput) -> dict[str, Any] | None:
        profile = await service.get_profile(default_user_id())
        return profile.model_dump(mode="json") if profile else None

    return ToolSpec(
        name="profile.read",
        description=(
            "Read the learner's persistent profile: goal, self-assessed level, "
            "weekly availability and format preferences. Returns null if the "
            "initial questionnaire hasn't been completed yet."
        ),
        input_model=EmptyInput,
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
