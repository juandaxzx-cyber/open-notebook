"""FastAPI app factory for the tutoring service (API-first, AGENTS.md rule #2)."""

import sys
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from tutor import __version__
from tutor.auth import AccessTokenStoreProtocol, build_resolve_user
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.llm.esperanto import EsperantoProvider
from tutor.llm.factory import MissingLLMConfigError, provider_from_env
from tutor.llm.fake import FakeProvider
from tutor.llm.interface import LLMProvider
from tutor.ownership import (
    SourceOwnerStore,
    SourceOwnerStoreProtocol,
    normalize_source_id,
)
from tutor.profile.models import default_user_id
from tutor.profile.router import build_router as build_profile_router
from tutor.profile.service import ProfileService
from tutor.session.engine import TutorEngine
from tutor.session.router import build_session_router
from tutor.session.store import SessionStore
from tutor.tools.defaults import build_default_registry
from tutor.usage import UsageCounterStore

UI_PATH = Path(__file__).parent / "ui" / "index.html"


class OpenNotebookStatus(BaseModel):
    reachable: bool
    indexed_sources: int | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    version: str
    open_notebook: OpenNotebookStatus


class UiConfigResponse(BaseModel):
    """Client-side configuration for the chat page (PR-F2, extended PR-F3,
    PR-W1).

    llm_provider/llm_model are surfaced for visibility only (never secrets —
    no API keys ever cross this endpoint)."""

    notebook_ui_url: str
    grounding_enabled: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    # PR-W1: lets the UI show the standing "cheaper ⇒ more errors" caveat
    # exactly when verification is on AND running the cheap profile.
    verify_turns: str = "off"
    verify_profile: str = "high"


class SourceCreateIn(BaseModel):
    """POST /sources/create body (PR-BT3): url XOR text — the two non-file
    ways OpenNotebook's `SourceCreate` supports (`api/models.py`), mapped to
    ON's `type: link|text` on the proxy side. Title is optional either way."""

    url: str | None = None
    text: str | None = None
    title: str | None = None


def _verifier_from_env(settings: TutorSettings, tutor_llm: LLMProvider) -> LLMProvider:
    """Resolve the PR-G2 verifier LLM. TUTOR_VERIFIER_PROVIDER/MODEL unset ⇒
    the tutor's own LLM instance (zero-key smoke keeps working). Warns when
    the resolved verifier is the same provider as the tutor's — same-family
    judging inflates scores (self-preference bias), same pattern as the E2
    eval judge warning."""
    verifier_provider = settings.verifier_provider or settings.llm_provider
    verifier_model = settings.verifier_model or settings.llm_model
    if verifier_provider == settings.llm_provider:
        print(
            "WARNING: verifier provider == tutor provider "
            f"({verifier_provider}). Same-family verification is a weaker "
            "check (self-preference bias); set TUTOR_VERIFIER_PROVIDER/MODEL.",
            file=sys.stderr,
        )
    if not settings.verifier_provider:
        return tutor_llm
    if (verifier_provider or "").lower() == "fake":
        return FakeProvider(model_name=verifier_model or "fake")
    return EsperantoProvider(
        provider=str(verifier_provider), model_name=str(verifier_model)
    )


def _build_engine(
    settings: TutorSettings, ownership_store: SourceOwnerStoreProtocol
) -> TutorEngine | None:
    """Engine is optional: without TUTOR_LLM_* config the session endpoints
    return 503 while the rest of the service keeps working."""
    try:
        llm = provider_from_env(settings)
    except MissingLLMConfigError:
        return None
    # PR-W1: the verifier is also the escalation generator for per-turn
    # verification, not just G2's memory consolidation — resolve it whenever
    # EITHER feature needs one, so disabling memory alone never silently
    # drops W1 down to a same-family (self-preferential) verifier.
    needs_verifier = settings.memory_enabled or settings.verify_turns != "off"
    verifier_llm = _verifier_from_env(settings, llm) if needs_verifier else llm
    return TutorEngine(
        llm=llm,
        registry=build_default_registry(settings),
        store=SessionStore(),
        user_id=default_user_id(),
        grounding_enabled=settings.grounding_enabled,
        memory_enabled=settings.memory_enabled,
        verifier_llm=verifier_llm,
        review_horizon_days=settings.review_horizon_days,
        verify_turns=settings.verify_turns,
        verify_profile=settings.verify_profile,
        grounding_budget_tokens=settings.grounding_budget_tokens,
        daily_turn_cap=settings.daily_turn_cap,
        usage_store=UsageCounterStore(),
        ownership_store=ownership_store,
    )


def create_app(
    settings: TutorSettings | None = None,
    client: OpenNotebookClient | None = None,
    profile_service: ProfileService | None = None,
    engine: TutorEngine | None = None,
    auth_store: AccessTokenStoreProtocol | None = None,
    ownership_store: SourceOwnerStoreProtocol | None = None,
) -> FastAPI:
    """Build the app. All dependencies are injectable for tests.

    `auth_store` (PR-BT1) lets tests exercise the real `Depends(resolve_user)`
    wiring over HTTP with a fake token store instead of a live SurrealDB —
    unused (never constructed) while `TUTOR_AUTH_ENABLED` is false.

    `ownership_store` (PR-BT3) is the same pattern: a real `SourceOwnerStore()`
    is always constructed here when the caller doesn't inject one (safe —
    construction never touches SurrealDB, same as `OpenNotebookClient()`
    above), so the live service always filters `/sources` and grounding by
    ownership. Tests that pass an explicit in-memory fake
    (`tutor.eval.fakes.InMemorySourceOwnerStore`) control exactly what's
    visible without a live database.
    """
    resolved = settings or TutorSettings.from_env()
    on_client = client or OpenNotebookClient(
        base_url=resolved.open_notebook_api_url,
        password=resolved.open_notebook_password,
    )
    owner_store: SourceOwnerStoreProtocol = ownership_store or SourceOwnerStore()

    app = FastAPI(title="Atenea Tutoring Service", version=__version__)
    # PR-BT1: one resolver per app instance, shared by both routers, so a
    # single Authorization header / `?t=` resolves to the same user_id
    # everywhere ("your own Atenea" — profile and sessions alike).
    resolve_user = build_resolve_user(resolved, auth_store)
    app.include_router(build_profile_router(profile_service, resolve_user))
    app.include_router(
        build_session_router(
            engine or _build_engine(resolved, owner_store), resolve_user
        )
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def ui() -> HTMLResponse:
        """Minimal chat page (PR-F1): single static file, no build step."""
        return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))

    @app.get("/config", response_model=UiConfigResponse)
    async def ui_config() -> UiConfigResponse:
        """Chat page config: "Notebooks" link (PR-F2), grounding toggle and
        provider/model visibility (PR-F3, no secrets — never the API key)."""
        return UiConfigResponse(
            notebook_ui_url=resolved.notebook_ui_url,
            grounding_enabled=resolved.grounding_enabled,
            llm_provider=resolved.llm_provider,
            llm_model=resolved.llm_model,
            verify_turns=resolved.verify_turns,
            verify_profile=resolved.verify_profile,
        )

    @app.get("/sources")
    async def sources(user_id: str = Depends(resolve_user)) -> list[dict[str, Any]]:
        """Material picker feed (PR-M1; PR-BT3 filters to own + public and
        flags the requester's own private uploads for the "privado" badge)."""
        try:
            all_sources = await on_client.list_sources()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
        if not all_sources:
            return list(all_sources)
        try:
            owner_rows = await owner_store.list_all()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
        owners = {normalize_source_id(r.get("source_id")): r for r in owner_rows}
        visible: list[dict[str, Any]] = []
        for item in all_sources:
            key = normalize_source_id(item.get("id", ""))
            row = owners.get(key)
            if row is None:
                visible.append({**item, "private": False})  # grandfathered => public
                continue
            is_public = bool(row.get("public"))
            is_owner = str(row.get("user_id")) == user_id
            if is_public or is_owner:
                visible.append({**item, "private": is_owner and not is_public})
        return visible

    @app.post("/sources/upload")
    async def upload_source(
        file: UploadFile = File(...),
        title: str | None = Form(None),
        user_id: str = Depends(resolve_user),
    ) -> dict[str, Any]:
        """PR-BT3: testers upload a file through the tutor (never touching
        OpenNotebook directly). Proxies to ON's multipart async-processing
        path, then writes a PRIVATE `source_owner` row for the requester."""
        content = await file.read()
        try:
            created = await on_client.create_source_from_file(
                file.filename or "upload",
                content,
                file.content_type,
                title=title,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
        return await _own_created_source(created, user_id)

    @app.post("/sources/create")
    async def create_source(
        payload: SourceCreateIn, user_id: str = Depends(resolve_user)
    ) -> dict[str, Any]:
        """PR-BT3: testers create a link or text source through the tutor.
        Proxies to ON's JSON async-processing path, then writes a PRIVATE
        `source_owner` row for the requester."""
        if bool(payload.url) == bool(payload.text):
            raise HTTPException(
                status_code=422, detail="Provide exactly one of 'url' or 'text'."
            )
        body: dict[str, Any] = {
            "type": "link" if payload.url else "text",
            "async_processing": True,
        }
        if payload.url:
            body["url"] = payload.url
        else:
            body["content"] = payload.text
        if payload.title:
            body["title"] = payload.title
        try:
            created = await on_client.create_source_json(body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
        return await _own_created_source(created, user_id)

    async def _own_created_source(
        created: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Write the PRIVATE ownership row for a just-created source. This is
        fatal (502), not a swallowed log: the entire point of BT3 is that a
        fresh upload never becomes silently public via the grandfather
        clause because its ownership row failed to write. The source already
        exists in OpenNotebook at this point — this slice does not attempt a
        rollback (no delete-source call is part of the BT3 client surface)."""
        source_id = str(created.get("id") or "")
        if not source_id:
            raise HTTPException(
                status_code=502, detail="OpenNotebook did not return a source id."
            )
        try:
            await owner_store.create(source_id, user_id, public=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Source created in OpenNotebook (id={source_id}) but "
                    f"privacy metadata failed to save: {type(exc).__name__}: "
                    f"{exc}. It may default to visible until this is fixed."
                ),
            ) from exc
        return {**created, "private": True}

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
