"""Phase 1 / task 1.11 — graph 接受 executor 參數。

Test 1: TradingAgentsGraph(executor="api") 跟不指定 executor 行為一致 (default)。
Test 2: GraphSetup accepts an executor parameter and threads it through nodes.
Test 3: 不合法 executor 名稱 raise clear ValueError。
Test 4: Node 經 executor.run_node 路徑跑時,APIExecutor 的 _callable shim 被觸發。

不在這檔測 actual LLM end-to-end(那是 phase 1 verify gate 用既有 108 tests
做 regression baseline)。只測 wiring。
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestGraphSetupAcceptsExecutor:
    def test_setup_signature_has_executor(self):
        import inspect

        from tradingagents.graph.setup import GraphSetup

        sig = inspect.signature(GraphSetup.__init__)
        assert "executor" in sig.parameters

    def test_setup_default_executor_is_api(self):
        from tradingagents.executors import APIExecutor
        from tradingagents.graph.conditional_logic import ConditionalLogic
        from tradingagents.graph.setup import GraphSetup

        setup = GraphSetup(
            quick_thinking_llm=MagicMock(),
            deep_thinking_llm=MagicMock(),
            tool_nodes={},
            conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
        )
        assert isinstance(setup.executor, APIExecutor)
        assert setup.executor.name == "api"


@pytest.mark.unit
class TestTradingAgentsGraphAcceptsExecutor:
    def test_init_signature_has_executor(self):
        import inspect

        from tradingagents.graph.trading_graph import TradingAgentsGraph

        sig = inspect.signature(TradingAgentsGraph.__init__)
        assert "executor" in sig.parameters

    def test_default_executor_is_api_string(self):
        """Default param value SHOULD be 'api' (string) so it round-trips
        config dicts and CLI flags naturally."""
        import inspect

        from tradingagents.graph.trading_graph import TradingAgentsGraph

        sig = inspect.signature(TradingAgentsGraph.__init__)
        default = sig.parameters["executor"].default
        assert default == "api"

    def test_invalid_executor_name_raises(self, mock_llm_client):
        """傳 invalid executor name 應 raise 明確 ValueError,
        不能 silent fallback。"""
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        with pytest.raises(ValueError, match="(?i)executor"):
            TradingAgentsGraph(
                selected_analysts=["market"],
                executor="totally-not-a-real-executor",
            )

    def test_executor_string_api_resolves_to_api_executor(self, mock_llm_client):
        """executor='api' 應該被 resolve 成 APIExecutor 實例。"""
        from tradingagents.executors import APIExecutor
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph(
            selected_analysts=["market"],
            executor="api",
        )
        assert isinstance(graph.graph_setup.executor, APIExecutor)

    def test_executor_instance_passes_through(self, mock_llm_client):
        """傳一個 NodeExecutor 實例(不是 string)也要接受。"""
        from tradingagents.executors import APIExecutor
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        my_executor = APIExecutor()
        graph = TradingAgentsGraph(
            selected_analysts=["market"],
            executor=my_executor,
        )
        assert graph.graph_setup.executor is my_executor


@pytest.mark.unit
class TestNodeRoutingThroughExecutor:
    """Node 函式被 executor.run_node 包過後仍 LangGraph-compatible。"""

    def test_wrap_node_returns_state_delta_dict(self):
        """`graph.setup` 包出來的 wrapped node 必須是 `state -> dict` 的純函式
        (LangGraph node 簽名)。內部走 executor.run_node 並回 NodeResult.state_delta。"""
        from tradingagents.executors import APIExecutor
        from tradingagents.graph.setup import _wrap_node_through_executor

        def fake_agent_fn(state):
            return {"market_report": f"analyzed_{state.get('company_of_interest', '?')}"}

        wrapped = _wrap_node_through_executor(
            executor=APIExecutor(),
            node_fn=fake_agent_fn,
            agent_role="market_analyst",
        )
        result = wrapped({"company_of_interest": "SPY"})
        assert isinstance(result, dict)
        assert result == {"market_report": "analyzed_SPY"}

    def test_wrap_node_propagates_executor_errors(self):
        """fake_agent_fn raise 時,wrapped 不該 swallow,要往上傳 ExecutorError 或原 error。"""
        from tradingagents.executors import APIExecutor, ExecutorError
        from tradingagents.graph.setup import _wrap_node_through_executor

        def broken_agent(state):
            raise RuntimeError("agent function blew up")

        wrapped = _wrap_node_through_executor(
            executor=APIExecutor(),
            node_fn=broken_agent,
            agent_role="trader",
        )
        # We accept either ExecutorError(reason="agent_error") or original RuntimeError
        with pytest.raises((ExecutorError, RuntimeError)):
            wrapped({"company_of_interest": "SPY"})
