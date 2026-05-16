"""Phase 1 / task 1.10 — NodeExecutor 抽象的契約測試。

這檔在 task 1.2-1.4 完成前刻意 RED。完成後應該全 GREEN,證明:
- types.py 暴露 NodeSpec / NodeResult / ExecutorError
- base.py 暴露 NodeExecutor Protocol(name / run_node / supports_structured)
- api.py 暴露 APIExecutor 且實作 NodeExecutor

不測 APIExecutor 的實際 LLM 行為(那是 test_api_executor.py / phase 1 verify gate
的 regression suite),只測介面契約。
"""

from typing import get_type_hints

import pytest


@pytest.mark.unit
class TestExecutorTypesExposed:
    def test_can_import_types_module(self):
        import tradingagents.executors.types  # noqa: F401

    def test_node_spec_is_constructible(self):
        from tradingagents.executors.types import NodeSpec

        spec = NodeSpec(
            agent_role="market_analyst",
            prompt_template="analyze {ticker}",
            tools=["get_stock_data"],
            schema=None,
            retry_policy={},
        )
        assert spec.agent_role == "market_analyst"
        assert spec.tools == ["get_stock_data"]

    def test_node_result_is_constructible(self):
        from tradingagents.executors.types import NodeResult

        result = NodeResult(
            state_delta={"market_report": "..."},
            raw_artifact_path=None,
            executor_metadata={"executor": "api"},
        )
        assert result.state_delta["market_report"] == "..."
        assert result.raw_artifact_path is None
        assert result.executor_metadata["executor"] == "api"

    def test_executor_error_is_raisable(self):
        from tradingagents.executors.types import ExecutorError

        err = ExecutorError(reason="timeout", node="bull_researcher", raw_error="...")
        assert err.reason == "timeout"
        assert err.node == "bull_researcher"
        # ExecutorError 應該是 Exception 子類,可被 raise/except
        assert isinstance(err, Exception)


@pytest.mark.unit
class TestNodeExecutorProtocol:
    def test_can_import_base_module(self):
        import tradingagents.executors.base  # noqa: F401

    def test_node_executor_protocol_exists(self):
        from tradingagents.executors.base import NodeExecutor

        # Protocol 本身應該可以被引用為 type;具體實作會在 api/claude_code 等檔
        assert NodeExecutor is not None

    def test_node_executor_signature(self):
        """Protocol 必須宣告 name, run_node, supports_structured 三個 member。"""
        from tradingagents.executors.base import NodeExecutor

        # Protocol 的成員以 attribute 暴露
        # name 是 instance attribute,run_node / supports_structured 是 method
        # 用 dir 檢查名稱出現即可,不檢查實現
        members = set(dir(NodeExecutor))
        assert "run_node" in members
        assert "supports_structured" in members
        # name 是 type-annotated class var,可能不出現在 dir;只要 hints 看得到
        hints = get_type_hints(NodeExecutor)
        assert "name" in hints


@pytest.mark.unit
class TestAPIExecutorImplementsProtocol:
    def test_can_import_api_executor(self):
        from tradingagents.executors.api import APIExecutor  # noqa: F401

    def test_api_executor_has_name_field(self):
        from tradingagents.executors.api import APIExecutor

        ex = APIExecutor()
        assert ex.name == "api"

    def test_api_executor_implements_protocol(self):
        """APIExecutor 必須是 NodeExecutor 的 structural subtype。"""
        from tradingagents.executors.api import APIExecutor
        from tradingagents.executors.base import NodeExecutor

        ex = APIExecutor()
        # Protocol structural subtyping 不靠 isinstance,改檢 attrs
        assert hasattr(ex, "name")
        assert callable(getattr(ex, "run_node", None))
        assert callable(getattr(ex, "supports_structured", None))
        # 額外:若 NodeExecutor 標 runtime_checkable,則 isinstance 也應通過
        try:
            assert isinstance(ex, NodeExecutor)
        except TypeError:
            # NodeExecutor 不是 runtime_checkable — structural check 已足
            pass

    def test_api_executor_supports_structured_returns_true(self):
        """API mode 用 langchain bind_structured,supports_structured 應 True。"""
        from tradingagents.executors.api import APIExecutor

        assert APIExecutor().supports_structured() is True


@pytest.mark.unit
class TestExecutorsModuleExports:
    """from tradingagents.executors import ... 主要符號應該可用。"""

    def test_top_level_exports(self):
        from tradingagents import executors

        for name in (
            "APIExecutor",
            "NodeExecutor",
            "NodeSpec",
            "NodeResult",
            "ExecutorError",
        ):
            assert hasattr(executors, name), f"executors module 缺 {name}"
