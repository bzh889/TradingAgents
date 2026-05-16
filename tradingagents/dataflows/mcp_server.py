"""MCP server exposing dataflows (yfinance / alpha_vantage) as 9 read-only tools.

Each tool is a thin transport wrapper around `interface.route_to_vendor(...)`,
preserving the existing vendor routing + fallback chain (yfinance hits
AlphaVantageRateLimitError -> falls back to alpha_vantage). API mode and
CLI mode share this server: API mode can opt in via env var (phase 4),
CLI mode wires through `claude --mcp-config` to fetch market data
from inside the subprocess.

The `mcp` SDK is loaded lazily so this module is importable without the
runtime dep — the unit test suite exercises the routing layer with
`route_to_vendor` mocked. Phase 4 (claude-code executor) is when the
running server becomes a runtime requirement.
"""

from __future__ import annotations

import sys
from typing import Optional


def route_to_vendor(method: str, *args, **kwargs):
    """Module-level lazy proxy to interface.route_to_vendor.

    Dogfood-found: importing `tradingagents.dataflows.interface` at module load
    pulls pandas + yfinance + alpha_vantage (~30s on a cold venv). Claude
    Code's `--mcp-config` probes the server immediately after spawn — if the
    process hasn't finished importing in time, claude reports "MCP servers
    are still connecting" and the agent gives up. Defer the heavy import to
    the first actual tool call so server startup is near-instant.

    Kept as a module-level callable (not a private `_route`) so unit tests
    that `patch("tradingagents.dataflows.mcp_server.route_to_vendor", ...)`
    continue to work — the patch shadows this proxy and the real interface
    module never loads under test.
    """
    from tradingagents.dataflows.interface import route_to_vendor as _impl

    return _impl(method, *args, **kwargs)


# Pre-declared tool names so tests can lock the exposed surface without
# inspecting FastMCP internals. Order matches design §3.3 + specs/dataflows-mcp.
TOOL_NAMES = (
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


# ---------------------------------------------------------------------------
# Module-level tool handlers (plain Python functions). FastMCP registers them
# as MCP tools in _build_server(); they are independently importable so the
# test suite can patch `route_to_vendor` and assert dispatch without spinning
# up the MCP server.
# ---------------------------------------------------------------------------


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)


def get_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int,
) -> str:
    return route_to_vendor(
        "get_indicators", symbol, indicator, curr_date, look_back_days
    )


def get_fundamentals(ticker: str, curr_date: Optional[str] = None) -> str:
    return route_to_vendor("get_fundamentals", ticker, curr_date)


def get_balance_sheet(
    ticker: str,
    freq: str = "quarterly",
    curr_date: Optional[str] = None,
) -> str:
    return route_to_vendor("get_balance_sheet", ticker, freq, curr_date)


def get_cashflow(
    ticker: str,
    freq: str = "quarterly",
    curr_date: Optional[str] = None,
) -> str:
    return route_to_vendor("get_cashflow", ticker, freq, curr_date)


def get_income_statement(
    ticker: str,
    freq: str = "quarterly",
    curr_date: Optional[str] = None,
) -> str:
    return route_to_vendor("get_income_statement", ticker, freq, curr_date)


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    return route_to_vendor("get_news", ticker, start_date, end_date)


def get_global_news(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 50,
) -> str:
    return route_to_vendor(
        "get_global_news", curr_date, look_back_days, limit
    )


def get_insider_transactions(ticker: str) -> str:
    return route_to_vendor("get_insider_transactions", ticker)


# ---------------------------------------------------------------------------
# MCP server construction (lazy)
# ---------------------------------------------------------------------------


def _build_server():
    """Build the FastMCP server. Returns None when `mcp` SDK is absent."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return None

    server = FastMCP("tradingagents-dataflows")

    # Register each module-level handler as an MCP tool. FastMCP infers the
    # JSON schema from the Python signature + type hints.
    for tool_name in TOOL_NAMES:
        handler = globals()[tool_name]
        server.tool(name=tool_name)(handler)

    return server


def main():
    server = _build_server()
    if server is None:
        sys.stderr.write(
            "dataflows.mcp_server requires the `mcp` SDK. Install it with "
            "`uv add mcp`. The 9 tool handlers (get_stock_data etc.) are still "
            "importable directly from `tradingagents.dataflows.mcp_server` for "
            "unit-test purposes; they delegate to `interface.route_to_vendor`.\n"
        )
        sys.exit(2)
    server.run()


if __name__ == "__main__":
    main()
