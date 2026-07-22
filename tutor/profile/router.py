"""Profile endpoints: GET /profile, PUT /profile."""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException

from tutor.auth import default_resolve_user
from tutor.profile.models import Profile, ProfileIn
from tutor.profile.service import ProfileService


def build_router(
    service: ProfileService | None = None,
    resolve_user: Callable[..., Awaitable[str]] | None = None,
) -> APIRouter:
    """Build the profile router. `service`/`resolve_user` are injectable for
    tests. `resolve_user` (PR-BT1) resolves the requester's user_id per
    request — `create_app` always builds a real one from settings; the
    fallback here only matters if this router is ever built standalone."""
    svc = service or ProfileService()
    resolve = resolve_user or default_resolve_user()
    router = APIRouter()

    @router.get("/profile", response_model=Profile)
    async def get_profile(user_id: str = Depends(resolve)) -> Profile:
        try:
            profile = await svc.get_profile(user_id)
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
    async def put_profile(
        payload: ProfileIn, user_id: str = Depends(resolve)
    ) -> Profile:
        try:
            return await svc.upsert_profile(user_id, payload)
        except Exception as exc:  # noqa: BLE001 — surface the real cause to the caller
            raise HTTPException(
                status_code=502, detail=f"Storage error: {exc}"
            ) from exc

    return router
