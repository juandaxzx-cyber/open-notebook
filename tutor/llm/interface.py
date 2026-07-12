"""Provider-agnostic LLM interface (fixed by the PR-B1 contract)."""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResponse(BaseModel):
    content: str
    provider: str
    model: str


class LLMProvider(Protocol):
    """Anything the tutor uses to complete a chat conversation."""

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse: ...
