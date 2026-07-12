"""Profile endpoints: GET /profile, PUT /profile."""

from fastapi import APIRouter, HTTPException

from tutor.profile.models import Profile, ProfileIn, default_user_id
from tutor.profile.service import ProfileService


def build_router(service: ProfileService | None = None) -> APIRouter:
    """Build the profile router. `service` is injectable for tests."""
    svc = service or ProfileService()
    router = APIRouter()

    @router.get("/profile", response_model=Profile)
    async def get_profile() -> Profile:
        profile = await svc.get_profile(default_user_id())
        if profile is None:
            raise HTTPException(
                status_code=404,
                detail="No profile yet — run `uv run python -m tutor.profile`.",
            )
        return profile

    @router.put("/profile", response_model=Profile)
    async def put_profile(payload: ProfileIn) -> Profile:
        return await svc.upsert_profile(default_user_id(), payload)

    return router
