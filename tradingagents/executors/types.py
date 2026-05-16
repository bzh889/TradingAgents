from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class NodeSpec:
    agent_role: str
    prompt_template: str = ""
    tools: list[str] = field(default_factory=list)
    schema: Optional[type] = None
    retry_policy: dict[str, Any] = field(default_factory=dict)
    # API mode shim: LangGraph-native node fn `(state) -> state_delta`.
    # CLI executors MUST ignore this field — they consume agent_role + prompt_template
    # + tools + schema and build a subprocess prompt. See design §D9.
    _callable: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None


@dataclass
class NodeResult:
    state_delta: dict[str, Any]
    raw_artifact_path: Optional[str] = None
    executor_metadata: dict[str, Any] = field(default_factory=dict)


class ExecutorError(Exception):
    def __init__(self, reason: str, node: str = "", raw_error: str = ""):
        self.reason = reason
        self.node = node
        self.raw_error = raw_error
        super().__init__(f"ExecutorError({reason}) at node={node}: {raw_error}")
