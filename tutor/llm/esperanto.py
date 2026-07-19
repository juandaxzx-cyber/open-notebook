"""Esperanto adapter — the ONLY tutor module allowed to import `esperanto`.

Call surface verified against open_notebook/ai/models.py and
open_notebook/ai/connection_tester.py: `AIFactory.create_language(...)` and
`await model.achat_complete(messages=[{"role": ..., "content": ...}])`,
whose response exposes `.content`. API keys are read by Esperanto from each
provider's standard environment variables.
"""

from collections.abc import Sequence
from typing import Any

from tutor.llm.interface import ChatMessage, ChatResponse


class EsperantoProvider:
    """LLMProvider implementation backed by an Esperanto language model."""

    def __init__(
        self,
        provider: str,
        model_name: str,
        esperanto_model: Any | None = None,  # injectable for tests
    ) -> None:
        self._provider = provider
        self._model_name = model_name
        if esperanto_model is None:
            from esperanto import AIFactory  # local import: keep esperanto contained

            esperanto_model = AIFactory.create_language(
                model_name=model_name,
                provider=provider,
            )
        self._model = esperanto_model

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        response = await self._model.achat_complete(
            messages=[{"role": m.role, "content": m.content} for m in messages]
        )
        # achat_complete's return type is a union with the streaming
        # AsyncGenerator; we never request streaming, so narrow via getattr
        # (CI mypy with the real esperanto types, 2026-07-19).
        content = getattr(response, "content", None)
        return ChatResponse(
            content=content or "",
            provider=self._provider,
            model=self._model_name,
        )
