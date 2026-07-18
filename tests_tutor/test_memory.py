"""PR-G2 — consolidated learner memory: recall, verified consolidation, the
store's CRUD/scoping, the `/memories` endpoint, and the disabled-path
backward-compat lock (byte-identical prompts, M1-style)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel

from tutor.app import create_app
from tutor.config import TutorSettings
from tutor.llm.fake import FakeProvider, FakeVerifierProvider
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session.engine import PROMPTS_DIR, TutorEngine, _render
from tutor.session.memory import (
    consolidate,
    normalize_topic_key,
    recall,
)
from tutor.session.models import ContentTraits, SessionState, TechniquePlan, Turn
from tutor.session.store import SessionStore, UnknownSessionError
from tutor.tools.registry import ToolRegistry, ToolSpec

CLASSIFY = (
    '{"verifiability": "verifiable", "structure": "hierarchical", '
    '"production": "apply"}'
)
CLOSE_JSON = (
    '{"summary": "covered vectors", "assessment": "solid start", '
    '"next_step": "practice dot products", "review_in_days": 3}'
)
VALID_NOTE_JSON = (
    '{"topic_key": "vectores", "topic_label": "Vectores", '
    '"summary": "engaged with vectors, made a first attempt", '
    '"mastery_estimate": 0.4, "recurring_errors": []}'
)
CLOSE_RECORD = {"summary": "covered vectors", "assessment": "solid start"}


# --- fakes ---


class FakeLLM:
    """Returns queued responses in order (mirrors tests_tutor/test_session.py)."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(
            content=self._contents.pop(0), provider="fake", model="fake"
        )


class FakeMemoryStore(SessionStore):
    """Dict-backed store: session CRUD (enough for engine-level tests) plus
    the PR-G2 memory CRUD surface `recall`/`consolidate` actually need."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.memories: dict[str, dict[str, Any]] = {}
        self._n = 0
        self._m = 0

    async def create(self, state: SessionState) -> str:
        self._n += 1
        sid = f"session:g2-{self._n}"
        self.records[sid] = {
            "id": sid,
            "user_id": state.user_id,
            "source_id": state.source_id,
            "topic": state.topic,
            "traits": state.traits.model_dump(),
            "technique": state.technique.model_dump(),
            "help": state.help.model_dump(),
            "task": state.task.model_dump(),
            "transcript": [t.model_dump() for t in state.transcript],
            "reviewed_ids": list(state.reviewed_ids),
        }
        return sid

    async def load(self, session_id: str) -> dict[str, Any]:
        try:
            return dict(self.records[session_id])
        except KeyError as exc:
            raise UnknownSessionError(session_id) from exc

    async def save_progress(self, state: SessionState) -> None:
        rec = self.records[state.session_id]
        rec["help"] = state.help.model_dump()
        rec["task"] = state.task.model_dump()
        rec["transcript"] = [t.model_dump() for t in state.transcript]

    async def close(
        self,
        session_id: str,
        summary: str,
        assessment: str,
        next_step: str,
        review_date: Any,
    ) -> None:
        self.records[session_id].update(
            summary=summary,
            assessment=assessment,
            next_step=next_step,
            review_date=review_date.isoformat() if review_date else None,
            ended_at="now",
        )

    async def list_for_user(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        return [r for r in self.records.values() if r["user_id"] == user_id]

    async def due_items(self, user_id: str, now: Any) -> list[dict[str, Any]]:
        return []

    async def record_review(
        self, session_ids: list[str], review_date: Any, graduate_at: int
    ) -> None:
        return None

    # --- memory CRUD (PR-G2) ---

    async def list_memories(self, user_id: str) -> list[dict[str, Any]]:
        rows = [m for m in self.memories.values() if m["user_id"] == user_id]
        return sorted(rows, key=lambda m: str(m.get("updated") or ""), reverse=True)

    async def upsert_memory(
        self,
        user_id: str,
        topic_key: str,
        topic_label: str,
        summary: str,
        mastery_estimate: float,
        recurring_errors: list[str],
        last_session_id: str | None,
    ) -> dict[str, Any]:
        self._m += 1
        existing = next(
            (
                m
                for m in self.memories.values()
                if m["user_id"] == user_id and m["topic_key"] == topic_key
            ),
            None,
        )
        if existing is not None:
            existing.update(
                topic_label=topic_label,
                summary=summary,
                mastery_estimate=mastery_estimate,
                recurring_errors=list(recurring_errors),
                sessions_count=int(existing.get("sessions_count") or 0) + 1,
                last_session_id=last_session_id,
                updated=f"{self._m:06d}",
            )
            return dict(existing)
        record_id = f"learner_memory:{self._m}"
        record = {
            "id": record_id,
            "user_id": user_id,
            "topic_key": topic_key,
            "topic_label": topic_label,
            "summary": summary,
            "mastery_estimate": mastery_estimate,
            "recurring_errors": list(recurring_errors),
            "sessions_count": 1,
            "last_session_id": last_session_id,
            "updated": f"{self._m:06d}",
        }
        self.memories[record_id] = record
        return dict(record)


class _Empty(BaseModel):
    pass


class _SearchArgs(BaseModel):
    query: str
    limit: int = 5


def _fake_registry() -> ToolRegistry:
    async def read_profile(_: _Empty) -> dict[str, Any]:
        return {
            "user_id": "juanda",
            "learning_goal": "linear algebra",
            "self_assessed_level": "beginner",
        }

    async def search(_: _SearchArgs) -> dict[str, Any]:
        return {"results": [{"title": "Vectors", "content": "A vector is..."}]}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "read", input_model=_Empty, handler=read_profile)
    )
    registry.register(
        ToolSpec("content.search", "search", input_model=_SearchArgs, handler=search)
    )
    return registry


def _state(
    topic: str = "vectores",
    transcript: list[Turn] | None = None,
    session_id: str = "session:x",
) -> SessionState:
    return SessionState(
        session_id=session_id,
        user_id="juanda",
        topic=topic,
        traits=ContentTraits(
            verifiability="verifiable", structure="hierarchical", production="apply"
        ),
        technique=TechniquePlan(primary="p", feedback_style="f", sequencing="s"),
        transcript=transcript
        or [
            Turn(role="learner", content="mi intento es 42"),
            Turn(role="tutor", content="bien, ¿y por qué crees que es 42?"),
        ],
    )


# --- fake provider (PR-G2 additions) ---


def test_fake_provider_consolidate_output_is_schema_valid_and_keyed_to_topic() -> None:
    prompt = [
        ChatMessage(
            role="user",
            content="Reflect on this tutoring episode ...\nTOPIC: vectores y matrices\n...",
        )
    ]
    data = json.loads(asyncio.run(FakeProvider().complete(prompt)).content)
    assert set(data) >= {
        "topic_key",
        "topic_label",
        "summary",
        "mastery_estimate",
        "recurring_errors",
    }
    assert data["topic_key"] == normalize_topic_key("vectores y matrices")


def test_fake_provider_verify_output_always_passes() -> None:
    prompt = [
        ChatMessage(
            role="user",
            content="Verify this consolidated learner-memory note ...\nTOPIC: x\n...",
        )
    ]
    data = json.loads(asyncio.run(FakeProvider().complete(prompt)).content)
    assert data == {"verdict": "pass", "violations": []}


def test_fake_verifier_provider_fails_first_then_passes() -> None:
    verifier = FakeVerifierProvider(fail_times=1)
    verify_prompt = [
        ChatMessage(
            role="user",
            content="Verify this consolidated learner-memory note ...\nTOPIC: x\n...",
        )
    ]
    first = json.loads(asyncio.run(verifier.complete(verify_prompt)).content)
    second = json.loads(asyncio.run(verifier.complete(verify_prompt)).content)
    assert first["verdict"] == "fail" and first["violations"]
    assert second["verdict"] == "pass"


# --- consolidate: new key / merge / malformed fallback ---


def test_consolidate_new_key_creates_note() -> None:
    store = FakeMemoryStore()
    state = _state()
    asyncio.run(
        consolidate(
            store, FakeProvider(), FakeProvider(), state, CLOSE_RECORD, enabled=True
        )
    )
    notes = asyncio.run(store.list_memories("juanda"))
    assert len(notes) == 1
    assert notes[0]["topic_key"] == normalize_topic_key("vectores")
    assert notes[0]["sessions_count"] == 1
    assert notes[0]["last_session_id"] == "session:x"


def test_consolidate_merges_into_existing_key() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        consolidate(
            store,
            FakeProvider(),
            FakeProvider(),
            _state(session_id="session:a"),
            CLOSE_RECORD,
            enabled=True,
        )
    )
    asyncio.run(
        consolidate(
            store,
            FakeProvider(),
            FakeProvider(),
            _state(session_id="session:b"),
            CLOSE_RECORD,
            enabled=True,
        )
    )
    notes = asyncio.run(store.list_memories("juanda"))
    assert len(notes) == 1  # same topic_key -> upsert, not a second row
    assert notes[0]["sessions_count"] == 2
    assert notes[0]["last_session_id"] == "session:b"


def test_consolidate_malformed_json_falls_back_to_deterministic_key() -> None:
    store = FakeMemoryStore()
    state = _state(topic="Cálculo Vectorial!!")
    # generator returns garbage -> fallback note; verifier then passes it.
    generator = FakeLLM(["not json at all", '{"verdict": "pass", "violations": []}'])
    asyncio.run(
        consolidate(store, generator, generator, state, CLOSE_RECORD, enabled=True)
    )
    notes = asyncio.run(store.list_memories("juanda"))
    assert len(notes) == 1
    assert notes[0]["topic_key"] == normalize_topic_key("Cálculo Vectorial!!")
    assert notes[0]["summary"] == CLOSE_RECORD["summary"]  # un-merged episode summary


def test_consolidate_disabled_is_a_no_op() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        consolidate(
            store, FakeProvider(), FakeProvider(), _state(), CLOSE_RECORD, enabled=False
        )
    )
    assert asyncio.run(store.list_memories("juanda")) == []


# --- verification: pass / fail-then-pass / double-fail ---


def test_verification_pass_writes_the_note() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        consolidate(
            store, FakeProvider(), FakeProvider(), _state(), CLOSE_RECORD, enabled=True
        )
    )
    assert len(asyncio.run(store.list_memories("juanda"))) == 1


def test_verification_fail_then_pass_writes_the_regenerated_note() -> None:
    store = FakeMemoryStore()
    verifier = FakeVerifierProvider(fail_times=1)
    asyncio.run(
        consolidate(
            store, FakeProvider(), verifier, _state(), CLOSE_RECORD, enabled=True
        )
    )
    notes = asyncio.run(store.list_memories("juanda"))
    assert len(notes) == 1
    assert verifier._verify_calls == 2  # first failed, regenerated, re-verified


def test_verification_double_fail_skips_the_write() -> None:
    store = FakeMemoryStore()
    verifier = FakeVerifierProvider(fail_times=2)
    asyncio.run(
        consolidate(
            store, FakeProvider(), verifier, _state(), CLOSE_RECORD, enabled=True
        )
    )
    assert asyncio.run(store.list_memories("juanda")) == []


def test_engine_close_survives_double_failed_verification() -> None:
    """The close record itself must never be lost to a bad reflection."""
    store = FakeMemoryStore()
    llm = FakeLLM([CLASSIFY, "opening", CLOSE_JSON, VALID_NOTE_JSON])
    engine = TutorEngine(
        llm=llm,
        registry=_fake_registry(),
        store=store,
        user_id="juanda",
        memory_enabled=True,
        verifier_llm=FakeVerifierProvider(fail_times=2),
    )
    state, _ = asyncio.run(engine.open("vectores"))
    record = asyncio.run(engine.close(state.session_id))
    assert record["summary"] == "covered vectors"  # close record intact
    assert asyncio.run(store.list_memories("juanda")) == []  # write skipped


def test_engine_close_writes_memory_on_verified_success() -> None:
    store = FakeMemoryStore()
    # No verifier_llm given -> defaults to the same `llm` (unset ⇒ tutor's own
    # LLM contract), so its queue also serves the generate + verify calls.
    llm = FakeLLM(
        [
            CLASSIFY,
            "opening",
            CLOSE_JSON,
            VALID_NOTE_JSON,
            '{"verdict": "pass", "violations": []}',
        ]
    )
    engine = TutorEngine(
        llm=llm,
        registry=_fake_registry(),
        store=store,
        user_id="juanda",
        memory_enabled=True,
    )
    state, _ = asyncio.run(engine.open("vectores"))
    asyncio.run(engine.close(state.session_id))
    notes = asyncio.run(store.list_memories("juanda"))
    assert len(notes) == 1
    assert notes[0]["topic_key"] == normalize_topic_key("vectores")


# --- recall: injected into the system prompt ---


def test_recall_is_injected_into_the_system_prompt() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        store.upsert_memory(
            user_id="juanda",
            topic_key=normalize_topic_key("vectores"),
            topic_label="Vectores",
            summary="ya domina la suma de vectores",
            mastery_estimate=0.7,
            recurring_errors=["confunde escalar con vector"],
            last_session_id=None,
        )
    )
    llm = FakeLLM([CLASSIFY, "opening"])
    engine = TutorEngine(
        llm=llm,
        registry=_fake_registry(),
        store=store,
        user_id="juanda",
        memory_enabled=True,
    )
    asyncio.run(engine.open("vectores"))
    prompt = llm.seen[-1][0].content
    assert "Learner memory" in prompt
    assert "ya domina la suma de vectores" in prompt
    assert "confunde escalar con vector" in prompt


def test_recall_empty_when_nothing_stored_yet() -> None:
    store = FakeMemoryStore()
    llm = FakeLLM([CLASSIFY, "opening"])
    engine = TutorEngine(
        llm=llm,
        registry=_fake_registry(),
        store=store,
        user_id="juanda",
        memory_enabled=True,
    )
    asyncio.run(engine.open("algo nuevo"))
    prompt = llm.seen[-1][0].content
    assert "Learner memory" not in prompt


# --- disabled memory: backward-compat lock (byte-identical prompts) ---


def test_disabled_memory_ignores_existing_notes_in_the_prompt() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        store.upsert_memory(
            user_id="juanda",
            topic_key=normalize_topic_key("vectores"),
            topic_label="Vectores",
            summary="ya domina la suma de vectores",
            mastery_estimate=0.9,
            recurring_errors=[],
            last_session_id=None,
        )
    )
    llm = FakeLLM([CLASSIFY, "opening"])
    engine = TutorEngine(
        llm=llm,
        registry=_fake_registry(),
        store=store,
        user_id="juanda",
        memory_enabled=False,  # TUTOR_MEMORY_ENABLED=false
    )
    asyncio.run(engine.open("vectores"))
    prompt = llm.seen[-1][0].content
    assert "Learner memory" not in prompt
    assert "{{memory_section}}" not in prompt


def _pre_g2_render(template_name: str, values: dict[str, str]) -> str:
    """Reconstruct the pre-G2 template by stripping just the
    `{{memory_section}}` placeholder line this PR appended, then render it
    with the exact same substitution + trailing-newline rules `_render` uses.
    """
    raw = (PROMPTS_DIR / template_name).read_text(encoding="utf-8")
    assert "{{memory_section}}" in raw
    pre_g2_template = raw.replace("{{memory_section}}", "")
    text = pre_g2_template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text.rstrip("\n") + "\n"


def test_session_prompt_disabled_memory_is_byte_identical_to_pre_g2() -> None:
    values = {
        "profile": "{}",
        "topic": "vectores",
        "traits": "{}",
        "technique_primary": "p",
        "technique_feedback": "f",
        "technique_sequencing": "s",
        "content": "some material",
        "help_state": "level 0",
        "task_state": "none",
    }
    expected = _pre_g2_render("session_system.md", values)
    actual = _render("session_system.md", {**values, "memory_section": ""})
    assert actual == expected


def test_review_prompt_disabled_memory_is_byte_identical_to_pre_g2() -> None:
    values = {
        "profile": "{}",
        "topic": "Repaso: x, y",
        "traits": "{}",
        "technique_primary": "retrieval practice",
        "technique_feedback": "contingent",
        "technique_sequencing": "interleaving prior topics",
        "content": "[1] x",
        "help_state": "level 0",
        "task_state": "none",
    }
    expected = _pre_g2_render("review_system.md", values)
    actual = _render("review_system.md", {**values, "memory_section": ""})
    assert actual == expected


# --- store CRUD + user scoping ---


def test_memory_store_upsert_and_user_scoping() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        store.upsert_memory(
            user_id="a",
            topic_key="k1",
            topic_label="K1",
            summary="s1",
            mastery_estimate=0.5,
            recurring_errors=[],
            last_session_id=None,
        )
    )
    asyncio.run(
        store.upsert_memory(
            user_id="b",
            topic_key="k1",
            topic_label="K1-b",
            summary="s2",
            mastery_estimate=0.2,
            recurring_errors=[],
            last_session_id=None,
        )
    )
    a_notes = asyncio.run(store.list_memories("a"))
    b_notes = asyncio.run(store.list_memories("b"))
    assert [n["topic_label"] for n in a_notes] == ["K1"]
    assert [n["topic_label"] for n in b_notes] == ["K1-b"]

    # same (user_id, topic_key) upserts in place instead of duplicating.
    asyncio.run(
        store.upsert_memory(
            user_id="a",
            topic_key="k1",
            topic_label="K1 updated",
            summary="s1b",
            mastery_estimate=0.6,
            recurring_errors=["e1"],
            last_session_id="session:z",
        )
    )
    a_notes2 = asyncio.run(store.list_memories("a"))
    assert len(a_notes2) == 1
    assert a_notes2[0]["topic_label"] == "K1 updated"
    assert a_notes2[0]["sessions_count"] == 2
    assert a_notes2[0]["last_session_id"] == "session:z"


def test_recall_matches_by_normalized_topic_and_ranks_related_by_recency() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        store.upsert_memory(
            user_id="juanda",
            topic_key=normalize_topic_key("otro tema"),
            topic_label="Otro tema",
            summary="s-otro",
            mastery_estimate=0.3,
            recurring_errors=[],
            last_session_id=None,
        )
    )
    asyncio.run(
        store.upsert_memory(
            user_id="juanda",
            topic_key=normalize_topic_key("Vectores"),
            topic_label="Vectores",
            summary="s-vectores",
            mastery_estimate=0.8,
            recurring_errors=[],
            last_session_id=None,
        )
    )
    ctx = asyncio.run(recall(store, "juanda", "vectores", enabled=True))
    assert ctx.note is not None
    assert ctx.note["topic_label"] == "Vectores"
    assert len(ctx.related) == 1
    assert ctx.related[0]["topic_label"] == "Otro tema"


# --- /memories endpoint: shape + scoping ---


def test_memories_endpoint_shape_and_scoping() -> None:
    store = FakeMemoryStore()
    asyncio.run(
        store.upsert_memory(
            user_id="juanda",
            topic_key="vectores",
            topic_label="Vectores",
            summary="s",
            mastery_estimate=0.42,
            recurring_errors=["e1"],
            last_session_id="session:x",
        )
    )
    asyncio.run(
        store.upsert_memory(
            user_id="otheruser",
            topic_key="vectores",
            topic_label="Otro",
            summary="s2",
            mastery_estimate=0.1,
            recurring_errors=[],
            last_session_id=None,
        )
    )
    engine = TutorEngine(
        llm=FakeLLM([]), registry=_fake_registry(), store=store, user_id="juanda"
    )
    app = create_app(settings=TutorSettings(), engine=engine)
    body = TestClient(app).get("/memories").json()

    assert len(body) == 1  # scoped to juanda only, otheruser's row excluded
    row = body[0]
    assert row["topic_key"] == "vectores"
    assert row["topic_label"] == "Vectores"
    assert row["summary"] == "s"
    assert row["mastery_estimate"] == 0.42
    assert row["recurring_errors"] == ["e1"]
    assert row["sessions_count"] == 1
    assert row["last_session_id"] == "session:x"


def test_memories_endpoint_empty_when_nothing_stored() -> None:
    engine = TutorEngine(
        llm=FakeLLM([]),
        registry=_fake_registry(),
        store=FakeMemoryStore(),
        user_id="juanda",
    )
    app = create_app(settings=TutorSettings(), engine=engine)
    response = TestClient(app).get("/memories")
    assert response.status_code == 200
    assert response.json() == []


# --- UI markup marker ---


def test_ui_has_progress_view() -> None:
    html = (Path(__file__).parent.parent / "tutor" / "ui" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="progress"' in html
    assert 'id="progress-link"' in html
    assert "loadProgress" in html
    assert "/memories" in html
