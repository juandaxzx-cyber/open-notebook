"""Session endpoints: GET /sessions, POST /session, POST /session/{id}/message,
POST /session/{id}/close, GET /session/{id}."""

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from tutor.session.engine import NoDueReviewError, NoProfileError, TutorEngine
from tutor.session.models import (
    DueItem,
    MemoryItem,
    MessageRequest,
    MessageResponse,
    SessionOpenRequest,
    SessionOpenResponse,
    SessionSummary,
)
from tutor.session.scheduling import retention
from tutor.session.store import UnknownSessionError, _to_naive_utc


def _status_of(record: dict[str, Any]) -> Literal["open", "closed"]:
    return "closed" if record.get("ended_at") else "open"


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

    def _bad_gateway(exc: Exception) -> HTTPException:
        """Surface the real cause (DB, OpenNotebook, LLM) instead of a mute 500."""
        return HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")

    @router.get("/sessions", response_model=list[SessionSummary])
    async def list_sessions(
        status: Literal["open", "closed"] | None = None,
    ) -> list[SessionSummary]:
        try:
            records = await _engine().list_sessions(status)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        summaries = []
        for record in records:
            help_state = record.get("help") or {}
            task_state = record.get("task") or {}
            summaries.append(
                SessionSummary(
                    session_id=str(record.get("id")),
                    topic=str(record.get("topic") or ""),
                    status=_status_of(record),
                    updated_at=str(
                        record.get("updated_at") or record.get("started_at") or ""
                    ),
                    task_index=int(task_state.get("index") or 0),
                    task_label=str(task_state.get("label") or ""),
                    help_level=int(help_state.get("help_level") or 0),
                    review_date=(
                        str(record["review_date"])
                        if record.get("review_date")
                        else None
                    ),
                )
            )
        return summaries

    @router.get("/reviews/due", response_model=list[DueItem])
    async def due_reviews() -> list[DueItem]:
        try:
            items = await _engine().due_reviews()
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        return [
            DueItem(
                session_id=str(record.get("id")),
                topic=str(record.get("topic") or ""),
                review_date=(
                    str(record["review_date"]) if record.get("review_date") else None
                ),
                next_step=(
                    str(record["next_step"]) if record.get("next_step") else None
                ),
                assessment=(
                    str(record["assessment"]) if record.get("assessment") else None
                ),
            )
            for record in items
        ]

    @router.get("/memories", response_model=list[MemoryItem])
    async def list_memories() -> list[MemoryItem]:
        """The learner's consolidated memory notes, recency-ordered
        (PR-G2) — "Tu progreso" in the UI."""
        try:
            records = await _engine().list_memories()
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        items = []
        for record in records:
            mastery = float(record.get("mastery_estimate") or 0.0)
            strength = float(record.get("strength") or 1.0)
            updated = record.get("updated")
            # PR-G3: retention is estimated at READ time from elapsed days
            # since this note was last touched; no `updated` yet (should not
            # happen post-create, but defensive) reads as "just now".
            elapsed_days = (
                (now_naive - _to_naive_utc(updated)).total_seconds() / 86400.0
                if updated
                else 0.0
            )
            items.append(
                MemoryItem(
                    topic_key=str(record.get("topic_key") or ""),
                    topic_label=str(record.get("topic_label") or ""),
                    summary=str(record.get("summary") or ""),
                    mastery_estimate=mastery,
                    recurring_errors=[
                        str(e) for e in (record.get("recurring_errors") or [])
                    ],
                    sessions_count=int(record.get("sessions_count") or 0),
                    last_session_id=(
                        str(record["last_session_id"])
                        if record.get("last_session_id")
                        else None
                    ),
                    updated=(str(updated) if updated else None),
                    estimated_retention=retention(mastery, strength, elapsed_days),
                )
            )
        return items

    @router.post("/review", response_model=SessionOpenResponse)
    async def open_review() -> SessionOpenResponse:
        try:
            state, opening = await _engine().open_review()
        except (NoProfileError, NoDueReviewError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        return SessionOpenResponse(
            session_id=state.session_id,
            opening_message=opening,
            traits=state.traits,
            technique=state.technique,
            task_index=state.task.index,
            task_label=state.task.label,
            verification_outcome=state.last_verification_outcome,
        )

    @router.post("/session", response_model=SessionOpenResponse)
    async def open_session(payload: SessionOpenRequest) -> SessionOpenResponse:
        try:
            state, opening = await _engine().open(payload.topic, payload.source_id)
        except NoProfileError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        return SessionOpenResponse(
            session_id=state.session_id,
            opening_message=opening,
            traits=state.traits,
            technique=state.technique,
            task_index=state.task.index,
            task_label=state.task.label,
            source_id=state.source_id,
            verification_outcome=state.last_verification_outcome,
        )

    @router.post("/session/{session_id}/message", response_model=MessageResponse)
    async def send_message(session_id: str, payload: MessageRequest) -> MessageResponse:
        try:
            state, reply = await _engine().message(session_id, payload.text)
        except UnknownSessionError as exc:
            raise HTTPException(status_code=404, detail="Unknown session") from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        return MessageResponse(
            reply=reply,
            attempts=state.help.attempts,
            help_level=state.help.help_level,
            task_index=state.task.index,
            task_label=state.task.label,
            verification_outcome=state.last_verification_outcome,
        )

    @router.post("/session/{session_id}/close")
    async def close_session(session_id: str) -> dict[str, Any]:
        try:
            record = await _engine().close(session_id)
        except UnknownSessionError as exc:
            raise HTTPException(status_code=404, detail="Unknown session") from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        record["id"] = str(record.get("id"))
        return record

    @router.get("/session/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        """Returns the stored record as-is (traits, technique, help, task,
        transcript, ...) plus `id` and `status`. Works for open sessions too
        (PR-R1): the transcript is persisted on every turn, so this is enough
        to re-render the whole conversation client-side."""
        try:
            record = await _engine().get(session_id)
        except UnknownSessionError as exc:
            raise HTTPException(status_code=404, detail="Unknown session") from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _bad_gateway(exc) from exc
        record["id"] = str(record.get("id"))
        record["status"] = _status_of(record)
        return record

    return router
