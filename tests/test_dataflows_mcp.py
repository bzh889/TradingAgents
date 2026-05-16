"""Phase 3 / task 3.3-3.4 — dataflows MCP server tool surface contract.

Phase 3 ships the MCP server as a separately-startable process; the actual
in-flight wiring to CLI executors happens in phase 4. These tests cover:
- Module importable; server builds with FastMCP when SDK is present
- All 9 expected tools registered with the right names
- Read-only check: zero write/set/delete/update verbs in tool names
- Each tool dispatches via `route_to_vendor` (verified by patching it)

Real network calls to yfinance / alpha_vantage are NOT exercised here —
that is integration territory and the existing 108-baseline suite covers
the routing layer through `route_to_vendor` directly.
"""

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestDataflowsMCPServerModuleExists:
    def test_can_import_module(self):
        import tradingagents.dataflows.mcp_server  # noqa: F401

    def test_module_exports_tool_handlers(self):
        from tradingagents.dataflows import mcp_server

        expected_handlers = (
            "get_stock_data",
            "get_indicators",
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        )
        for name in expected_handlers:
            assert hasattr(mcp_server, name), f"mcp_server 缺 {name}"

    def test_build_server_returns_fastmcp_instance(self):
        from tradingagents.dataflows.mcp_server import _build_server

        server = _build_server()
        assert server is not None
        assert server.name == "tradingagents-dataflows"


@pytest.mark.unit
class TestDataflowsToolsRouteThroughVendor:
    """Each MCP tool MUST dispatch through `route_to_vendor`; the server is a
    thin transport wrapper, not a re-implementation of routing."""

    def test_get_stock_data_routes(self):
        from tradingagents.dataflows.mcp_server import get_stock_data

        with patch(
            "tradingagents.dataflows.mcp_server.route_to_vendor",
            return_value="<stub-data>",
        ) as mock_router:
            result = get_stock_data(
                symbol="SPY", start_date="2024-05-01", end_date="2024-05-10"
            )
        mock_router.assert_called_once_with(
            "get_stock_data", "SPY", "2024-05-01", "2024-05-10"
        )
        assert result == "<stub-data>"

    def test_get_indicators_routes(self):
        from tradingagents.dataflows.mcp_server import get_indicators

        with patch(
            "tradingagents.dataflows.mcp_server.route_to_vendor",
            return_value="<stub>",
        ) as mock_router:
            get_indicators(
                symbol="SPY",
                indicator="rsi",
                curr_date="2024-05-10",
                look_back_days=30,
            )
        mock_router.assert_called_once()
        assert mock_router.call_args.args[0] == "get_indicators"

    def test_get_fundamentals_routes(self):
        from tradingagents.dataflows.mcp_server import get_fundamentals

        with patch(
            "tradingagents.dataflows.mcp_server.route_to_vendor",
            return_value="<stub>",
        ) as mock_router:
            get_fundamentals(ticker="SPY", curr_date="2024-05-10")
        mock_router.assert_called_once_with(
            "get_fundamentals", "SPY", "2024-05-10"
        )

    def test_get_news_routes(self):
        from tradingagents.dataflows.mcp_server import get_news

        with patch(
            "tradingagents.dataflows.mcp_server.route_to_vendor",
            return_value="<stub>",
        ) as mock_router:
            get_news(
                ticker="SPY", start_date="2024-05-01", end_date="2024-05-10"
            )
        mock_router.assert_called_once_with(
            "get_news", "SPY", "2024-05-01", "2024-05-10"
        )

    def test_get_global_news_with_optional_args(self):
        from tradingagents.dataflows.mcp_server import get_global_news

        with patch(
            "tradingagents.dataflows.mcp_server.route_to_vendor",
            return_value="<stub>",
        ) as mock_router:
            # Both with and without optional args
            get_global_news(curr_date="2024-05-10")
            get_global_news(curr_date="2024-05-10", look_back_days=14, limit=100)
        assert mock_router.call_count == 2

    def test_get_insider_transactions_routes(self):
        from tradingagents.dataflows.mcp_server import get_insider_transactions

        with patch(
            "tradingagents.dataflows.mcp_server.route_to_vendor",
            return_value="<stub>",
        ) as mock_router:
            get_insider_transactions(ticker="SPY")
        mock_router.assert_called_once_with("get_insider_transactions", "SPY")


@pytest.mark.unit
class TestDataflowsToolsReadOnly:
    """No tool name in the server may suggest write / mutation behaviour.
    Spec: specs/dataflows-mcp/spec.md `Requirement: Dataflows MCP 不暴露任何
    寫盤操作`."""

    def test_no_write_verbs_in_tool_names(self):
        from tradingagents.dataflows.mcp_server import TOOL_NAMES

        forbidden_prefixes = ("set_", "write_", "delete_", "update_", "post_", "put_")
        for tool_name in TOOL_NAMES:
            for prefix in forbidden_prefixes:
                assert not tool_name.startswith(prefix), (
                    f"Tool '{tool_name}' uses forbidden write-verb prefix '{prefix}'. "
                    f"Dataflows MCP MUST be read-only."
                )

    def test_tool_count_is_nine(self):
        """Lock the exposed surface — if we add a tool, design.md §3.3 plus this
        test must be updated together."""
        from tradingagents.dataflows.mcp_server import TOOL_NAMES

        assert len(TOOL_NAMES) == 9, (
            f"Expected 9 dataflows tools, got {len(TOOL_NAMES)}. "
            f"If adding/removing tools, update specs/dataflows-mcp/spec.md too."
        )
