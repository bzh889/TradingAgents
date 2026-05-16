from typing import Union

from .api import APIExecutor
from .base import NodeExecutor
from .claude_code import ClaudeCodeExecutor
from .codex import CodexExecutor
from .gemini import GeminiExecutor
from .types import ExecutorError, NodeResult, NodeSpec

# All 4 executor names ship as of phase 5.
_KNOWN_EXECUTORS = {"api", "claude-code", "codex", "gemini"}


def resolve_executor(value: Union[str, NodeExecutor]) -> NodeExecutor:
    """Resolve a string name or NodeExecutor instance into a NodeExecutor.

    Phase 1: 'api'. Phase 4: 'claude-code'. Phase 5: 'codex' / 'gemini'.
    Unknown names raise ValueError.
    """
    if isinstance(value, str):
        name = value
        if name == "api":
            return APIExecutor()
        if name == "claude-code":
            return ClaudeCodeExecutor()
        if name == "codex":
            return CodexExecutor()
        if name == "gemini":
            return GeminiExecutor()
        raise ValueError(
            f"Unknown executor name '{name}'. Valid options: {sorted(_KNOWN_EXECUTORS)}."
        )
    # Assume the caller passed a NodeExecutor instance; do a soft duck-type check.
    if not hasattr(value, "run_node") or not hasattr(value, "name"):
        raise ValueError(
            f"executor must be a string name or NodeExecutor instance; got {type(value).__name__}."
        )
    return value


__all__ = [
    "APIExecutor",
    "ClaudeCodeExecutor",
    "CodexExecutor",
    "GeminiExecutor",
    "NodeExecutor",
    "NodeSpec",
    "NodeResult",
    "ExecutorError",
    "resolve_executor",
]
