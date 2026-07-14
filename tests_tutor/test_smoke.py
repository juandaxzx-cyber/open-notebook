"""Tests for the fake provider and the in-process smoke journey (PR-DX2)."""

from __future__ import annotations

import asyncio
import json

from tutor.config import TutorSettings
from tutor.llm.factory import provider_from_env
from tutor.llm.fake import FakeProvider
from tutor.llm.interface import ChatMessage

# --- fake provider ---

_CLASSIFY = [ChatMessage(role="user", content="Classify the following study topic")]
_OPEN = [
    ChatMessage(role="system", content="sys"),
    ChatMessage(role="user", content="Open the session: greet me and give a task."),
]
_CLOSE = [
    ChatMessage(
        role="user",
        content="The tutoring session below is ending. Produce its closing record.",
    )
]
_HELP = [
    ChatMessage(role="system", content="sys"),
    ChatMessage(role="assistant", content="[[TASK: x]] hi"),
    ChatMessage(role="user", content="no sé, dame una pista"),
]
_ATTEMPT = [
    ChatMessage(role="system", content="sys"),
    ChatMessage(role="assistant", content="[[TASK: x]] hi"),
    ChatMessage(role="user", content="mi intento es 42"),
]


def _complete(provider: FakeProvider, messages: list[ChatMessage]) -> str:
    return asyncio.run(provider.complete(messages)).content


def test_factory_selects_fake_provider_without_model() -> None:
    settings = TutorSettings(llm_provider="fake")  # no model set
    provider = provider_from_env(settings)
    assert isinstance(provider, FakeProvider)


def test_fake_classify_output_parses_to_traits() -> None:
    data = json.loads(_complete(FakeProvider(), _CLASSIFY))
    assert set(data) == {"verifiability", "structure", "production"}
    assert data["verifiability"] in {"verifiable", "interpretive"}


def test_fake_close_output_parses_to_record() -> None:
    data = json.loads(_complete(FakeProvider(), _CLOSE))
    assert set(data) >= {"summary", "assessment", "next_step", "review_in_days"}
    assert isinstance(data["review_in_days"], int)


def test_fake_open_carries_task_marker() -> None:
    assert "[[TASK:" in _complete(FakeProvider(), _OPEN)


def test_fake_help_reply_is_a_hint_not_the_answer() -> None:
    reply = _complete(FakeProvider(), _HELP)
    assert "hint" in reply.lower()
    assert "[[TASK:" not in reply  # a plain turn must not open a new task


def test_fake_provider_is_deterministic() -> None:
    provider = FakeProvider()
    for messages in (_CLASSIFY, _OPEN, _CLOSE, _HELP, _ATTEMPT):
        assert _complete(provider, messages) == _complete(provider, messages)


def test_fake_model_name_is_accepted_but_free() -> None:
    resp = asyncio.run(FakeProvider("whatever-model").complete(_ATTEMPT))
    assert resp.provider == "fake"
    assert resp.model == "whatever-model"


# --- smoke journey ---


def test_smoke_journey_in_process_passes() -> None:
    from tutor.smoke import run

    assert run() == 0
