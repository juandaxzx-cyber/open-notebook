"""FastAPI app factory for the tutoring service (API-first, AGENTS.md rule #2)."""

from fastapi import FastAPI
from pydantic import BaseModel

from tutor import __version__
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.llm.factory import MissingLLMConfigError, provider_from_env
from tutor.profile.models import default_user_id
from tutor.profile.router import build_router as build_profile_router
from tutor.profile.service import ProfileService
from tutor.session.engine import TutorEngine
from tutor.session.router import build_session_router
from tutor.session.store import SessionStore
from tutor.tools.defaults import build_default_registry


class OpenNotebookStatus(BaseModel):
    reachable: bool
    indexed_sources: int | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    version: str
    open_notebook: OpenNotebookStatus


def _build_engine(settings: TutorSettings) -> TutorEngine | None:
    """Engine is optional: without TUTOR_LLM_* config the session endpoints
    return 503 while the rest of the service keeps working."""
    try:
        llm = provider_from_env(settings)
    except MissingLLMConfigError:
        return None
    return TutorEngine(
        llm=llm,
        registry=build_default_registry(settings),
        store=SessionStore(),
        user_id=default_user_id(),
    )


def create_app(
    settings: TutorSettings | None = None,
    client: OpenNotebookClient | None = None,
    profile_service: ProfileService | None = None,
    engine: TutorEngine | None = None,
) -> FastAPI:
    """Build the app. All dependencies are injectable for tests."""
    resolved = settings or TutorSettings.from_env()
    on_client = client or OpenNotebookClient(
        base_url=resolved.open_notebook_api_url,
        password=resolved.open_notebook_password,
    )

    app = FastAPI(title="Atenea Tutoring Service", version=__version__)
    app.include_router(build_profile_router(profile_service))
    app.include_router(build_session_router(engine or _build_engine(resolved)))

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
