from typing import Union

from .api import APIExecutor
from .base import NodeExecutor
from .types import ExecutorError, NodeResult, NodeSpec

# Known executor names. Phase 1 ships `api` only; phase 4/5 add CLI executors.
_KNOWN_EXECUTORS = {"api", "claude-code", "codex", "gemini"}


def resolve_executor(value: Union[str, NodeExecutor]) -> NodeExecutor:
    """Resolve a string name or NodeExecutor instance into a NodeExecutor.

    Phase 1: only `api` resolves. Names in _KNOWN_EXECUTORS but not yet
    implemented raise NotImplementedError (so the CLI selector stub can
    point to a meaningful error). Unknown names raise ValueError.
    """
    if isinstance(value, str):
        name = value
        if name == "api":
            return APIExecutor()
        if name in _KNOWN_EXECUTORS:
            raise NotImplementedError(
                f"Executor '{name}' is declared but not implemented yet. "
                f"Phase 1 ships 'api' only; '{name}' lands in phase 4 (claude-code) "
                f"or phase 5 (codex/gemini). See openspec/changes/cli-llm-rearch/tasks.md."
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
    "NodeExecutor",
    "NodeSpec",
    "NodeResult",
    "ExecutorError",
    "resolve_executor",
]
