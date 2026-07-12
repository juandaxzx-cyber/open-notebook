import asyncio
from typing import Any

import pytest

from tutor.config import TutorSettings
from tutor.llm.esperanto import EsperantoProvider
from tutor.llm.factory import MissingLLMConfigError, provider_from_env
from tutor.llm.interface import ChatMessage


class FakeEsperantoResponse:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeEsperantoModel:
    def __init__(self, content: str | None = "hello") -> None:
        self._content = content
        self.seen_messages: list[dict[str, str]] | None = None

    async def achat_complete(
        self, messages: list[dict[str, str]]
    ) -> FakeEsperantoResponse:
        self.seen_messages = messages
        return FakeEsperantoResponse(self._content)


def test_adapter_converts_messages_and_wraps_response() -> None:
    fake = FakeEsperantoModel(content="bonjour")
    provider = EsperantoProvider(
        provider="anthropic", model_name="claude-x", esperanto_model=fake
    )
    response = asyncio.run(
        provider.complete(
            [
                ChatMessage(role="system", content="be brief"),
                ChatMessage(role="user", content="hi"),
            ]
        )
    )

    assert fake.seen_messages == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]
    assert response.content == "bonjour"
    assert response.provider == "anthropic"
    assert response.model == "claude-x"


def test_adapter_handles_empty_content() -> None:
    provider = EsperantoProvider(
        provider="openai",
        model_name="gpt-x",
        esperanto_model=FakeEsperantoModel(content=None),
    )
    response = asyncio.run(provider.complete([ChatMessage(role="user", content="hi")]))
    assert response.content == ""


def test_factory_raises_without_config() -> None:
    settings = TutorSettings()  # no llm_provider / llm_model
    with pytest.raises(MissingLLMConfigError):
        provider_from_env(settings)


def test_factory_builds_provider_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, Any] = {}

    class FakeProvider:
        def __init__(self, provider: str, model_name: str) -> None:
            built["provider"] = provider
            built["model_name"] = model_name

    monkeypatch.setattr("tutor.llm.factory.EsperantoProvider", FakeProvider)
    settings = TutorSettings(llm_provider="ollama", llm_model="gemma3")

    result = provider_from_env(settings)

    assert isinstance(result, FakeProvider)
    assert built == {"provider": "ollama", "model_name": "gemma3"}


def test_settings_read_llm_vars_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_LLM_PROVIDER", "vertex")
    monkeypatch.setenv("TUTOR_LLM_MODEL", "gemini-x")
    settings = TutorSettings.from_env()
    assert settings.llm_provider == "vertex"
    assert settings.llm_model == "gemini-x"
