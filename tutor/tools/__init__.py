"""Tool registry (Feature D): every tutor capability is a registry entry.

New capabilities are added as new ToolSpec entries — never surgery on the
tutor (AGENTS.md hard rule #5). Descriptions are written for LLM consumption:
PR-E1 feeds `list_specs()` into function calling.
"""

from tutor.tools.registry import (
    DuplicateToolError,
    ToolRegistry,
    ToolSpec,
    UnknownToolError,
)

__all__ = ["DuplicateToolError", "ToolRegistry", "ToolSpec", "UnknownToolError"]
