"""FastAPI app factory for the tutoring service (API-first, AGENTS.md rule #2)."""

from fastapi import FastAPI
from pydantic import BaseModel

from tutor import __version__
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.profile.router import build_router as build_profile_router
from tutor.profile.service import ProfileService


class OpenNotebookStatus(BaseModel):
    reachable: bool
    indexed_sources: int | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    version: str
    open_notebook: OpenNotebookStatus


def create_app(
    settings: TutorSettings | None = None,
    client: OpenNotebookClient | None = None,
    profile_service: ProfileService | None = None,
) -> FastAPI:
    """Build the app. `settings`/`client`/`profile_service` are injectable for tests."""
    resolved = settings or TutorSettings.from_env()
    on_client = client or OpenNotebookClient(
        base_url=resolved.open_notebook_api_url,
        password=resolved.open_notebook_password,
    )

    app = FastAPI(title="Atenea Tutoring Service", version=__version__)
    app.include_router(build_profile_router(profile_service))

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        try:
            count = await on_client.count_indexed_sources()
        except Exception as exc:  # noqa: BLE001 — unreachable ON is a state, not a crash
            return HealthResponse(
                status="degraded",
                version=__version__,
                open_notebook=OpenNotebookStatus(reachable=False, error=str(exc)),
            )
        return HealthResponse(
            status="ok",
            version=__version__,
            open_notebook=OpenNotebookStatus(reachable=True, indexed_sources=count),
        )

    return app
