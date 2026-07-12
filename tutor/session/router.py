"""Session endpoints: POST /session, POST /session/{id}/message,
POST /session/{id}/close, GET /session/{id}."""

from typing import Any

from fastapi import APIRouter, HTTPException

from tutor.session.engine import NoProfileError, TutorEngine
from tutor.session.models import (
    MessageRequest,
    MessageResponse,
    SessionOpenRequest,
    SessionOpenResponse,
)
from tutor.session.store import UnknownSessionError


def build_session_router(engine: TutorEngine | None) -> APIRouter:
    router = APIRouter()

    def _engine() -> TutorEngine:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Tutor LLM not configured: set TUTOR_LLM_PROVIDER and "
                    "TUTOR_LLM_MODEL (see .env.example)."
                ),
            )
        return engine

    @router.post("/session", response_model=SessionOpenResponse)
    async def open_session(payload: SessionOpenRequest) -> SessionOpenResponse:
        try:
            state, opening = await _engine().open(payload.topic)
        except NoProfileError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SessionOpenResponse(
            session_id=state.session_id,
            opening_message=opening,
            traits=state.traits,
            technique=state.technique,
        )

    @router.post("/session/{session_id}/message", response_model=MessageResponse)
    async def send_message(session_id: str, payload: MessageRequest) -> MessageResponse:
        try:
            state, reply = await _engine().message(session_id, payload.text)
        except UnknownSessionError as exc:
            raise HTTPException(status_code=404, detail="Unknown session") from exc
        return MessageResponse(
            reply=reply, attempts=state.help.attempts, help_level=state.help.help_level
        )

    @router.post("/session/{session_id}/close")
    async def close_session(session_id: str) -> dict[str, Any]:
        try:
            record = await _engine().close(session_id)
        except UnknownSessionError as exc:
            raise HTTPException(status_code=404, detail="Unknown session") from exc
        record["id"] = str(record.get("id"))
        return record

    @router.get("/session/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        try:
            record = await _engine().get(session_id)
        except UnknownSessionError as exc:
            raise HTTPException(status_code=404, detail="Unknown session") from exc
        record["id"] = str(record.get("id"))
        return record

    return router
