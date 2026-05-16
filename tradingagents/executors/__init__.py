from typing import Union

from .api import APIExecutor
from .base import NodeExecutor
from .claude_code import ClaudeCodeExecutor
from .types import ExecutorError, NodeResult, NodeSpec

# Known executor names. Phase 4 ships claude-code; codex/gemini remain phase 5.
_KNOWN_EXECUTORS = {"api", "claude-code", "codex", "gemini"}
_PHASE_5_PENDING = {"codex", "gemini"}


def resolve_executor(value: Union[str, NodeExecutor]) -> NodeExecutor:
    """Resolve a string name or NodeExecutor instance into a NodeExecutor.

    Phase 1: 'api'. Phase 4: 'claude-code'. Phase 5: 'codex' / 'gemini'.
    Names in _KNOWN_EXECUTORS but not yet implemented raise
    NotImplementedError so the CLI selector stub can re-prompt with a
    meaningful message. Unknown names raise ValueError.
    """
    if isinstance(value, str):
        name = value
        if name == "api":
            return APIExecutor()
        if name == "claude-code":
            return ClaudeCodeExecutor()
        if name in _PHASE_5_PENDING:
            raise NotImplementedError(
                f"Executor '{name}' lands in phase 5. See openspec/changes/"
                f"cli-llm-rearch/tasks.md §5."
            )
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
    "NodeExecutor",
    "NodeSpec",
    "NodeResult",
    "ExecutorError",
    "resolve_executor",
]
