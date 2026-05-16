from typing import Any, Protocol, runtime_checkable

from .types import NodeResult, NodeSpec


@runtime_checkable
class NodeExecutor(Protocol):
    name: str

    def run_node(
        self,
        node_name: str,
        state: dict[str, Any],
        spec: NodeSpec,
    ) -> NodeResult: ...

    def supports_structured(self) -> bool: ...
