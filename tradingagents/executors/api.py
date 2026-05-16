from typing import Any

from .types import ExecutorError, NodeResult, NodeSpec


class APIExecutor:
    """Wraps existing langchain ChatModel path through the NodeExecutor
    interface. CLI executors (claude-code / codex / gemini) implement the
    same protocol; the graph treats them uniformly.

    Per design §D9: API mode uses NodeSpec._callable as the shim — the
    existing `create_*(llm) -> callable(state) -> state_delta` agent
    functions are passed as opaque callables. APIExecutor never re-implements
    agent logic; it delegates. This keeps the `tradingagents/agents/**`
    promise of zero modification intact.
    """

    name: str = "api"

    def supports_structured(self) -> bool:
        # API mode uses langchain `bind_structured(llm, schema)` inside each
        # agent function. APIExecutor itself does not enforce schema validation;
        # that is the agent's job. supports_structured() reports capability,
        # not active enforcement.
        return True

    def run_node(
        self,
        node_name: str,
        state: dict[str, Any],
        spec: NodeSpec,
    ) -> NodeResult:
        if spec._callable is None:
            raise ExecutorError(
                reason="no_callable",
                node=node_name,
                raw_error=(
                    "APIExecutor requires NodeSpec._callable to be set. "
                    "graph/setup.py wraps each create_*(llm) result into "
                    "NodeSpec(_callable=fn). See design §D9."
                ),
            )
        state_delta = spec._callable(state)
        return NodeResult(
            state_delta=state_delta,
            raw_artifact_path=None,
            executor_metadata={
                "executor": "api",
                "agent_role": spec.agent_role,
            },
        )
