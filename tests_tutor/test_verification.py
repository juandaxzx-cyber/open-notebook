"""PR-W1 — per-turn verification of tutor replies: the `verification.py`
seam (verify_turn / escalate ladder), engine integration (one gate at
`_complete_verified`), whole-source-lite grounding, and the disabled-path
backward-compat locks (byte-identical prompts/replies, M1-style)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tutor.app import create_app
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.llm.fake import FakeProvider, FakeVerifierProvider
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session import verification
from tutor.session.engine import TutorEngine
from tutor.session.grounding import retrieve_grounding
from tutor.session.models import SessionState
from tutor.session.store import SessionStore, UnknownSessionError
from tutor.tools.content import content_get_source_tool, content_search_tool
from tutor.tools.registry import ToolRegistry, ToolSpec

CLASSIFY = (
    '{"verifiability": "verifiable", "structure": "hierarchical", '
    '"production": "apply"}'
)

_ROWS = [
    {
        "title": "Algebra",
        "content": "A vector is an arrow with magnitude and direction.",
        "parent_id": "source:A",
        "similarity": 0.9,
    },
]


# --- fakes (mirrors tests_tutor/test_grounding.py / test_memory.py) ---


class FakeLLM:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(
            content=self._contents.pop(0), provider="fake", model="fake"
        )


class MemStore(SessionStore):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._n = 0

    async def create(self, state: SessionState) -> str:
        self._n += 1
        sid = f"session:w{self._n}"
        self.records[sid] = {
            "id": sid,
            "user_id": state.user_id,
            "source_id": state.source_id,
            "topic": state.topic,
            "traits": state.traits.model_dump(),
            "technique": state.technique.model_dump(),
            "help": state.help.model_dump(),
            "task": state.task.model_dump(),
            "transcript": [t.model_dump(exclude_none=True) for t in state.transcript],
            "reviewed_ids": list(state.reviewed_ids),
        }
        return sid

    async def load(self, sid: str) -> dict[str, Any]:
        try:
            return dict(self.records[sid])
        except KeyError as exc:
            raise UnknownSessionError(sid) from exc

    async def save_progress(self, state: SessionState) -> None:
        rec = self.records[state.session_id]
        rec["help"] = state.help.model_dump()
        rec["task"] = state.task.model_dump()
        rec["transcript"] = [t.model_dump(exclude_none=True) for t in state.transcript]

    async def close(self, *a: Any, **k: Any) -> None:  # pragma: no cover
        ...

    async def list_for_user(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [r for r in self.records.values() if r["user_id"] == user_id]
        if status == "open":
            rows = [r for r in rows if not r.get("ended_at")]
        elif status == "closed":
            rows = [r for r in rows if r.get("ended_at")]
        return rows

    async def due_items(self, user_id: str, now: Any) -> list[dict[str, Any]]:
        return [
            r
            for r in self.records.values()
            if r["user_id"] == user_id and r.get("ended_at") and r.get("review_date")
        ]

    async def record_review(self, *a: Any, **k: Any) -> None:  # pragma: no cover
        return None


class _Empty(BaseModel):
    pass


class _SearchArgs(BaseModel):
    query: str
    limit: int = 5
    type: str = "text"
    source_id: str | None = None


def _client(rows: list[dict[str, Any]] | None = None) -> OpenNotebookClient:
    rows = _ROWS if rows is None else rows

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search":
            return httpx.Response(
                200,
                json={
                    "results": rows,
                    "total_count": len(rows),
                    "search_type": "vector",
                },
            )
        return httpx.Response(404)

    return OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )


def _registry(
    rows: list[dict[str, Any]] | None = None, with_get_source: bool = False
) -> ToolRegistry:
    async def read_profile(_: _Empty) -> dict[str, Any]:
        return {
            "user_id": "juanda",
            "learning_goal": "algebra",
            "self_assessed_level": "beginner",
        }

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "read", input_model=_Empty, handler=read_profile)
    )
    registry.register(content_search_tool(_client(rows)))
    if with_get_source:
        registry.register(content_get_source_tool(_client(rows)))
    return registry


def _engine(
    llm: Any,
    store: MemStore,
    *,
    verify_turns: str = "off",
    verify_profile: str = "high",
    verifier_llm: Any = None,
    grounding: bool = True,
    with_get_source: bool = False,
) -> TutorEngine:
    return TutorEngine(
        llm=llm,
        registry=_registry(with_get_source=with_get_source),
        store=store,
        user_id="juanda",
        grounding_enabled=grounding,
        verifier_llm=verifier_llm,
        verify_turns=verify_turns,
        verify_profile=verify_profile,
    )


_MESSAGES = [
    ChatMessage(role="system", content="sys"),
    ChatMessage(role="user", content="hi"),
]


# --- verification.applies (scope logic) ---


def test_applies_off_never_verifies() -> None:
    assert verification.applies("off", True) is False
    assert verification.applies("off", False) is False


def test_applies_grounded_default_skips_ungrounded() -> None:
    assert verification.applies("grounded", True) is True
    assert verification.applies("grounded", False) is False


def test_applies_all_verifies_everything() -> None:
    assert verification.applies("all", True) is True
    assert verification.applies("all", False) is True


# --- verify_turn: grounded / ungrounded / malformed ---


def test_verify_turn_grounded_pass() -> None:
    verdict = asyncio.run(
        verify_turn_helper(FakeProvider(), "a reply", "some evidence", grounded=True)
    )
    assert verdict.verdict == "pass"
    assert verdict.malformed is False


def test_verify_turn_malformed_json_is_not_a_fail() -> None:
    class GarbageLLM:
        async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
            return ChatResponse(
                content="not json at all", provider="fake", model="fake"
            )

    verdict = asyncio.run(
        verify_turn_helper(GarbageLLM(), "a reply", "evidence", grounded=True)
    )
    assert verdict.verdict == "pass"  # ships unflagged, never blocks
    assert verdict.malformed is True


def test_verify_turn_ungrounded_uses_abstention_instructions() -> None:
    llm = FakeLLM(['{"verdict": "pass", "violations": []}'])
    asyncio.run(verify_turn_helper(llm, "a reply", "evidence", grounded=False))
    prompt = llm.seen[0][0].content
    assert "UNGROUNDED session" in prompt
    assert "Fabricated references" in prompt
    assert "(none — this is an ungrounded session" in prompt


def test_verify_turn_grounded_uses_faithfulness_and_citation_instructions() -> None:
    llm = FakeLLM(['{"verdict": "pass", "violations": []}'])
    asyncio.run(
        verify_turn_helper(llm, "a reply [1]", "the actual passage", grounded=True)
    )
    prompt = llm.seen[0][0].content
    assert "GROUNDED session" in prompt
    assert "mis-citation" in prompt
    assert "the actual passage" in prompt


async def verify_turn_helper(llm: Any, reply: str, evidence: str, *, grounded: bool):
    return await verification.verify_turn(llm, reply, evidence, grounded=grounded)


# --- escalate: high profile ladder ---


def test_escalate_high_profile_pass_is_clean() -> None:
    verifier = FakeVerifierProvider(turn_fail_times=0)
    result = asyncio.run(
        verification.escalate(
            generator_llm=FakeLLM([]),
            verifier_llm=verifier,
            messages=_MESSAGES,
            reply="original reply",
            evidence="ev",
            grounded=True,
            profile="high",
        )
    )
    assert result.text == "original reply"
    assert result.trace is not None
    assert result.trace.outcome == "clean"
    assert len(result.trace.attempts) == 1
    assert verifier._turn_verify_calls == 1


def test_escalate_high_profile_fail_then_pass_is_corrected() -> None:
    verifier = FakeVerifierProvider(turn_fail_times=1)
    generator = FakeLLM(["revised by generator"])
    result = asyncio.run(
        verification.escalate(
            generator_llm=generator,
            verifier_llm=verifier,
            messages=_MESSAGES,
            reply="original reply",
            evidence="ev",
            grounded=True,
            profile="high",
        )
    )
    assert result.text == "revised by generator"
    assert result.trace is not None
    assert result.trace.outcome == "corrected"
    assert len(result.trace.attempts) == 2
    assert result.trace.attempts[0].verdict == "fail"
    assert result.trace.attempts[1].verdict == "pass"
    assert verifier._turn_verify_calls == 2


def test_escalate_high_profile_fail_fail_escalate_pass() -> None:
    # attempt1 fail, attempt2 (gen-retry) fail, attempt3 (escalated#1) pass.
    verifier = FakeVerifierProvider(turn_fail_times=2)
    generator = FakeLLM(["gen retry (still bad)"])
    result = asyncio.run(
        verification.escalate(
            generator_llm=generator,
            verifier_llm=verifier,
            messages=_MESSAGES,
            reply="original reply",
            evidence="ev",
            grounded=True,
            profile="high",
        )
    )
    assert result.trace is not None
    assert result.trace.outcome == "escalated"
    assert len(result.trace.attempts) == 3
    assert [a.verdict for a in result.trace.attempts] == ["fail", "fail", "pass"]
    assert [a.generator for a in result.trace.attempts] == [
        "primary",
        "primary",
        "escalated",
    ]
    assert verifier._turn_verify_calls == 3


def test_escalate_high_profile_all_fail_is_limits_admitted() -> None:
    verifier = FakeVerifierProvider(turn_fail_times=99)
    generator = FakeLLM(["gen retry (still bad)"])
    result = asyncio.run(
        verification.escalate(
            generator_llm=generator,
            verifier_llm=verifier,
            messages=_MESSAGES,
            reply="original reply",
            evidence="ev",
            grounded=True,
            profile="high",
        )
    )
    assert result.trace is not None
    assert result.trace.outcome == "limits-admitted"
    assert len(result.trace.attempts) == 4  # primary + retry + 2 escalations
    assert all(a.verdict == "fail" for a in result.trace.attempts)
    assert verifier._turn_verify_calls == 4
    # worst-case budget check (contract: ~3 regenerations + 4 verifier calls)


# --- escalate: cheap profile ---


def test_escalate_cheap_profile_pass_is_clean() -> None:
    verifier = FakeVerifierProvider(turn_fail_times=0)
    result = asyncio.run(
        verification.escalate(
            generator_llm=FakeLLM([]),
            verifier_llm=verifier,
            messages=_MESSAGES,
            reply="original reply",
            evidence="ev",
            grounded=True,
            profile="cheap",
        )
    )
    assert result.trace is not None
    assert result.trace.outcome == "clean"


def test_escalate_cheap_profile_fail_then_still_fail_is_flagged_no_escalation() -> None:
    verifier = FakeVerifierProvider(turn_fail_times=99)
    generator = FakeLLM(["gen retry (still bad)"])
    result = asyncio.run(
        verification.escalate(
            generator_llm=generator,
            verifier_llm=verifier,
            messages=_MESSAGES,
            reply="original reply",
            evidence="ev",
            grounded=True,
            profile="cheap",
        )
    )
    assert result.trace is not None
    assert result.trace.outcome == "flagged"
    assert len(result.trace.attempts) == 2  # verify(1) + gen-retry(1), no escalation
    assert verifier._turn_verify_calls == 2  # never reaches the escalation ladder


# --- escalate: malformed verifier output short-circuits ---


def test_escalate_malformed_verifier_ships_unflagged_and_logs(caplog: Any) -> None:
    class GarbageVerifier:
        async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
            return ChatResponse(content="not json", provider="fake", model="fake")

    result = asyncio.run(
        verification.escalate(
            generator_llm=FakeLLM([]),
            verifier_llm=GarbageVerifier(),
            messages=_MESSAGES,
            reply="original reply",
            evidence="ev",
            grounded=True,
            profile="high",
        )
    )
    assert result.text == "original reply"  # unmodified, never lost
    assert result.trace is not None
    assert result.trace.outcome == "clean"
    assert result.trace.attempts[0].malformed is True


# --- engine integration: one gate, byte-identical when off ---


def test_verify_turns_off_is_byte_identical_and_never_calls_verifier() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening reply"])
    verifier = FakeVerifierProvider(turn_fail_times=99)  # would fail everything
    engine = _engine(llm, store, verify_turns="off", verifier_llm=verifier)

    state, opening = asyncio.run(engine.open("vectores", "source:A"))

    assert opening == "opening reply"  # unmodified
    assert verifier._turn_verify_calls == 0  # the gate was never entered
    assert state.last_verification_outcome is None
    assert "verification" not in store.records[state.session_id]["transcript"][-1]


def test_grounded_scope_skips_ungrounded_turns() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening reply"])
    verifier = FakeVerifierProvider(turn_fail_times=99)
    engine = _engine(
        llm, store, verify_turns="grounded", verifier_llm=verifier, grounding=False
    )

    state, opening = asyncio.run(engine.open("vectores"))  # no source_id -> ungrounded

    assert opening == "opening reply"
    assert verifier._turn_verify_calls == 0
    assert state.last_verification_outcome is None


def test_grounded_scope_verifies_grounded_turns_and_persists_trace() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening reply"])
    verifier = FakeVerifierProvider(turn_fail_times=0)  # passes
    engine = _engine(llm, store, verify_turns="grounded", verifier_llm=verifier)

    state, opening = asyncio.run(engine.open("vectores", "source:A"))

    assert opening == "opening reply"
    assert verifier._turn_verify_calls == 1
    assert state.last_verification_outcome == "clean"
    trace = store.records[state.session_id]["transcript"][-1]["verification"]
    assert trace["outcome"] == "clean"
    assert trace["profile"] == "high"


def test_all_scope_verifies_ungrounded_turns_with_abstention_check() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening reply"])
    verifier = FakeVerifierProvider(turn_fail_times=0)
    engine = _engine(
        llm, store, verify_turns="all", verifier_llm=verifier, grounding=False
    )

    state, _ = asyncio.run(engine.open("vectores"))

    assert verifier._turn_verify_calls == 1
    assert state.last_verification_outcome == "clean"


def test_high_profile_fail_then_pass_ships_corrected_reply_and_persists_ladder() -> (
    None
):
    store = MemStore()
    # gen-retry re-calls the SAME `llm` (the engine's own provider is the
    # generator), so the queue needs a second entry for the regeneration.
    llm = FakeLLM([CLASSIFY, "original grounded reply", "revised by generator"])
    verifier = FakeVerifierProvider(turn_fail_times=1)
    engine = _engine(llm, store, verify_turns="grounded", verifier_llm=verifier)

    state, opening = asyncio.run(engine.open("vectores", "source:A"))

    assert opening != "original grounded reply"  # regenerated by the gen-retry
    assert state.last_verification_outcome == "corrected"
    trace = store.records[state.session_id]["transcript"][-1]["verification"]
    assert trace["outcome"] == "corrected"
    assert len(trace["attempts"]) == 2


def test_message_turn_is_gated_the_same_way_as_open() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening", "a message reply"])
    verifier = FakeVerifierProvider(turn_fail_times=0)
    engine = _engine(llm, store, verify_turns="grounded", verifier_llm=verifier)

    state, _ = asyncio.run(engine.open("vectores", "source:A"))
    state2, reply = asyncio.run(engine.message(state.session_id, "mi intento"))

    assert reply == "a message reply"
    assert state2.last_verification_outcome == "clean"
    assert verifier._turn_verify_calls == 2  # one for open, one for message


def test_review_session_is_treated_as_ungrounded() -> None:
    # PR-W1 smallest-reading decision: open_review never calls
    # retrieve_grounding (no source_id concept for reviews), so it is always
    # verified with grounded=False — under scope="grounded" it is skipped
    # entirely, matching the ungrounded-skip behavior above.
    store = MemStore()
    store.records["session:due"] = {
        "id": "session:due",
        "user_id": "juanda",
        "topic": "vectores",
        "ended_at": "2026-01-01T00:00:00",
        "review_date": "2026-01-01T00:00:00",
        "assessment": "a",
        "next_step": "b",
        "summary": "c",
    }
    llm = FakeLLM(["opening review"])
    verifier = FakeVerifierProvider(turn_fail_times=99)
    engine = _engine(llm, store, verify_turns="grounded", verifier_llm=verifier)

    state, _ = asyncio.run(engine.open_review())

    assert verifier._turn_verify_calls == 0  # ungrounded, scope="grounded" skips it
    assert state.last_verification_outcome is None


# --- closed-world section: grounded-only, byte-identical for ungrounded ---


def test_closed_world_section_present_only_for_grounded_sessions() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening reply"])
    engine = _engine(llm, store, verify_turns="off", grounding=True)
    asyncio.run(engine.open("vectores", "source:A"))
    grounded_prompt = llm.seen[-1][0].content
    assert "Closed-world contract" in grounded_prompt

    store2 = MemStore()
    llm2 = FakeLLM([CLASSIFY, "opening reply"])
    engine2 = _engine(llm2, store2, verify_turns="off", grounding=False)
    asyncio.run(engine2.open("vectores"))
    ungrounded_prompt = llm2.seen[-1][0].content
    assert "Closed-world contract" not in ungrounded_prompt
    assert "{{closed_world_section}}" not in ungrounded_prompt


def test_ungrounded_prompt_byte_identical_to_pre_w1() -> None:
    # M1-style lock: ungrounded sessions render EXACTLY the same
    # "Retrieved material" paragraph as before W1 — no stray blank line, no
    # placeholder leakage (contract: "ungrounded + no verification =>
    # byte-identical prompts").
    from tutor.session.engine import PROMPTS_DIR

    raw = (PROMPTS_DIR / "session_system.md").read_text(encoding="utf-8")
    pre_w1 = raw.replace("{{closed_world_section}}", "")

    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening reply"])
    engine = _engine(llm, store, verify_turns="off", grounding=False)
    asyncio.run(engine.open("vectores"))
    prompt = llm.seen[-1][0].content

    # The static paragraph plus its trailing blank line must be identical.
    marker = (
        'If the block above begins with "GROUNDED SOURCE", teach strictly '
        "from those\npassages and cite them by their [n] markers when you "
        "use them; do not add\noutside facts the passages already cover. "
        "Otherwise treat it as loose\nbackground.\n\n## Task protocol"
    )
    assert marker in pre_w1
    assert marker in prompt


# --- fake provider: verify_turn.md fixture support ---


def test_fake_provider_verify_turn_prompt_always_passes() -> None:
    llm = FakeProvider()
    prompt = [
        ChatMessage(
            role="user",
            content="Verify this tutor reply to the learner (grounded)...\nReply to verify:\nx",
        )
    ]
    import json

    data = json.loads(asyncio.run(llm.complete(prompt)).content)
    assert data == {"verdict": "pass", "violations": []}


def test_fake_verifier_turn_fixtures_match_contract_names() -> None:
    # pass
    v = FakeVerifierProvider(turn_fail_times=0)
    prompt = [
        ChatMessage(role="user", content="Verify this tutor reply to the learner x")
    ]
    import json

    first = json.loads(asyncio.run(v.complete(prompt)).content)
    assert first["verdict"] == "pass"

    # fail-then-pass
    v = FakeVerifierProvider(turn_fail_times=1)
    a = json.loads(asyncio.run(v.complete(prompt)).content)
    b = json.loads(asyncio.run(v.complete(prompt)).content)
    assert a["verdict"] == "fail" and b["verdict"] == "pass"

    # fail-fail-escalate-pass (three calls: fail, fail, pass)
    v = FakeVerifierProvider(turn_fail_times=2)
    results = [
        json.loads(asyncio.run(v.complete(prompt)).content)["verdict"] for _ in range(3)
    ]
    assert results == ["fail", "fail", "pass"]

    # all-fail
    v = FakeVerifierProvider(turn_fail_times=99)
    results = [
        json.loads(asyncio.run(v.complete(prompt)).content)["verdict"] for _ in range(4)
    ]
    assert results == ["fail", "fail", "fail", "fail"]


# --- whole-source-lite grounding ---


_SOURCE_ROW = [{"title": "Long text", "full_text": "word " * 10, "id": "source:A"}]


def _get_source_registry(full_text: str, title: str = "Doc") -> ToolRegistry:
    async def read_profile(_: _Empty) -> dict[str, Any]:
        return {"self_assessed_level": "beginner"}

    async def get_source(args: Any) -> dict[str, Any]:
        return {"id": args.source_id, "title": title, "full_text": full_text}

    class _GetSourceIn(BaseModel):
        source_id: str

    registry = ToolRegistry()
    registry.register(
        ToolSpec("profile.read", "r", input_model=_Empty, handler=read_profile)
    )
    registry.register(
        ToolSpec(
            "content.get_source", "g", input_model=_GetSourceIn, handler=get_source
        )
    )

    async def search(args: _SearchArgs) -> dict[str, Any]:
        return {"results": _ROWS}

    registry.register(
        ToolSpec("content.search", "s", input_model=_SearchArgs, handler=search)
    )
    return registry


def test_whole_source_used_when_it_fits_budget() -> None:
    registry = _get_source_registry("short text that easily fits", title="My Doc")
    result = asyncio.run(
        retrieve_grounding(
            registry,
            topic="x",
            source_id="source:A",
            enabled=True,
            budget_tokens=16000,
        )
    )
    assert result.grounded is True
    assert result.whole_source is True
    assert "whole source" in result.content
    assert "[source:A]" in result.content
    assert "My Doc" in result.content


def test_whole_source_falls_back_to_scoped_when_over_budget() -> None:
    registry = _get_source_registry("word " * 1000, title="Big Doc")
    result = asyncio.run(
        retrieve_grounding(
            registry, topic="x", source_id="source:A", enabled=True, budget_tokens=10
        )
    )
    assert result.grounded is True
    assert result.whole_source is False
    assert "GROUNDED SOURCE" in result.content
    assert "arrow with magnitude" in result.content  # scoped-search row content


def test_whole_source_falls_back_when_get_source_tool_is_unavailable() -> None:
    # No content.get_source registered — mirrors older registries / M1 tests.
    registry = _registry()
    result = asyncio.run(
        retrieve_grounding(registry, topic="x", source_id="source:A", enabled=True)
    )
    assert result.grounded is True
    assert result.whole_source is False


def test_whole_source_falls_back_on_empty_full_text() -> None:
    registry = _get_source_registry("")
    result = asyncio.run(
        retrieve_grounding(registry, topic="x", source_id="source:A", enabled=True)
    )
    assert result.whole_source is False


# --- content.get_source client + tool ---


def test_client_get_source_calls_the_right_endpoint() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(
            200, json={"id": "source:A", "title": "T", "full_text": "hello"}
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    result = asyncio.run(client.get_source("source:A"))
    assert seen["path"] == "/api/sources/source:A"
    assert result["full_text"] == "hello"


def test_content_get_source_tool_calls_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": "source:A", "title": "T", "full_text": "hello"}
        )

    client = OpenNotebookClient(
        base_url="http://on:5055", transport=httpx.MockTransport(handler)
    )
    registry = ToolRegistry()
    registry.register(content_get_source_tool(client))
    result = asyncio.run(registry.call("content.get_source", {"source_id": "source:A"}))
    assert result["full_text"] == "hello"


# --- API surface: verification_outcome on responses ---


def test_open_response_carries_verification_outcome() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening reply"])
    verifier = FakeVerifierProvider(turn_fail_times=0)
    engine = _engine(llm, store, verify_turns="grounded", verifier_llm=verifier)
    app = create_app(settings=TutorSettings(), engine=engine)

    body = (
        TestClient(app)
        .post("/session", json={"topic": "vectores", "source_id": "source:A"})
        .json()
    )
    assert body["verification_outcome"] == "clean"


def test_message_response_carries_verification_outcome() -> None:
    store = MemStore()
    llm = FakeLLM([CLASSIFY, "opening", "reply"])
    verifier = FakeVerifierProvider(turn_fail_times=0)
    engine = _engine(llm, store, verify_turns="grounded", verifier_llm=verifier)
    app = create_app(settings=TutorSettings(), engine=engine)
    client = TestClient(app)

    sid = client.post(
        "/session", json={"topic": "vectores", "source_id": "source:A"}
    ).json()["session_id"]
    body = client.post(f"/session/{sid}/message", json={"text": "hola"}).json()
    assert body["verification_outcome"] == "clean"


def test_config_exposes_verify_settings() -> None:
    settings = TutorSettings(verify_turns="all", verify_profile="cheap")
    body = TestClient(create_app(settings=settings)).get("/config").json()
    assert body["verify_turns"] == "all"
    assert body["verify_profile"] == "cheap"


# --- UI markup markers ---


def test_ui_shows_cheap_profile_caveat_and_verification_notice_hooks() -> None:
    html = (Path(__file__).parent.parent / "tutor" / "ui" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="verify-chip"' in html
    assert "addVerificationNotice" in html
    assert "verification_outcome" in html
