"""Build the configured LLMProvider from environment-based settings."""

from tutor.config import TutorSettings
from tutor.llm.esperanto import EsperantoProvider
from tutor.llm.fake import FakeProvider
from tutor.llm.interface import LLMProvider


class MissingLLMConfigError(RuntimeError):
    """Raised when TUTOR_LLM_PROVIDER / TUTOR_LLM_MODEL are not configured."""


def provider_from_env(settings: TutorSettings | None = None) -> LLMProvider:
    resolved = settings or TutorSettings.from_env()
    if (resolved.llm_provider or "").lower() == "fake":
        # Deterministic offline provider (PR-DX2): no esperanto, no keys, no
        # network. The model name is read but unused — any value is accepted.
        return FakeProvider(model_name=resolved.llm_model or "fake")
    if not resolved.llm_provider or not resolved.llm_model:
        raise MissingLLMConfigError(
            "Set TUTOR_LLM_PROVIDER and TUTOR_LLM_MODEL in the environment "
            "(see .env.example). API keys use each provider's standard variables."
        )
    return EsperantoProvider(
        provider=resolved.llm_provider,
        model_name=resolved.llm_model,
    )
