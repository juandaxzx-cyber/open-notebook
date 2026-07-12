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
        try:
            profile = await svc.get_profile(default_user_id())
        except Exception as exc:  # noqa: BLE001 — surface the real cause to the caller
            raise HTTPException(
                status_code=502, detail=f"Storage error: {exc}"
            ) from exc
        if profile is None:
            raise HTTPException(
                status_code=404,
                detail="No profile yet — run `uv run python -m tutor.profile`.",
            )
        return profile

    @router.put("/profile", response_model=Profile)
    async def put_profile(payload: ProfileIn) -> Profile:
        try:
            return await svc.upsert_profile(default_user_id(), payload)
        except Exception as exc:  # noqa: BLE001 — surface the real cause to the caller
            raise HTTPException(
                status_code=502, detail=f"Storage error: {exc}"
            ) from exc

    return router
