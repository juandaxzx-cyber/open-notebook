"""Uniform discover/call interface for tutor tools (PR-D1 contract)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class UnknownToolError(KeyError):
    pass


class DuplicateToolError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str  # namespaced: "content.search", "profile.read"...
    description: str  # LLM-facing
    input_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[Any]]  # receives the validated input_model


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise DuplicateToolError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(
                f"Unknown tool: {name}. Available: {sorted(self._tools)}"
            ) from exc

    def list_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_model.model_json_schema(),
            }
            for spec in self._tools.values()
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        spec = self.get(name)
        payload = spec.input_model.model_validate(arguments)
        return await spec.handler(payload)
