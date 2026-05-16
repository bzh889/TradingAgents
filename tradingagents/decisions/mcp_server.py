"""MCP server exposing the decisions submission API as MCP tools.

The submission callables live in `tradingagents.decisions` (this package's
`__init__`). This module is the MCP transport wrapper. CLI executors
(claude-code / codex / gemini) spawn this server and connect via
`--mcp-config`; the executor then receives schema-valid decisions as MCP
tool-call payloads rather than parsing stdout.

The `mcp` SDK is loaded lazily so the rest of the project (including the
108-baseline API-mode tests) doesn't require it as a hard dependency. Phase
4 (claude-code executor) is when MCP becomes a runtime requirement.
"""

from __future__ import annotations

import sys

from tradingagents.decisions import (
    submit_portfolio_decision,
    submit_research_plan,
    submit_trader_proposal,
)


def _build_server():
    """Build the MCP server lazily. Returns None if the `mcp` SDK is absent."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return None

    server = FastMCP("tradingagents-decisions")

    @server.tool()
    def submit_research_plan_tool(
        recommendation: str,
        rationale: str,
        strategic_actions: str,
    ) -> dict:
        """Submit a ResearchPlan; returns the validated dict."""
        return submit_research_plan(
            recommendation=recommendation,
            rationale=rationale,
            strategic_actions=strategic_actions,
        ).model_dump()

    @server.tool()
    def submit_trader_proposal_tool(
        action: str,
        reasoning: str,
        entry_price: float | None = None,
        stop_loss: float | None = None,
        position_sizing: str | None = None,
    ) -> dict:
        """Submit a TraderProposal; returns the validated dict."""
        return submit_trader_proposal(
            action=action,
            reasoning=reasoning,
            entry_price=entry_price,
            stop_loss=stop_loss,
            position_sizing=position_sizing,
        ).model_dump()

    @server.tool()
    def submit_portfolio_decision_tool(
        rating: str,
        executive_summary: str,
        investment_thesis: str,
        price_target: float | None = None,
        time_horizon: str | None = None,
    ) -> dict:
        """Submit a PortfolioDecision; returns the validated dict."""
        return submit_portfolio_decision(
            rating=rating,
            executive_summary=executive_summary,
            investment_thesis=investment_thesis,
            price_target=price_target,
            time_horizon=time_horizon,
        ).model_dump()

    return server


def main():
    server = _build_server()
    if server is None:
        sys.stderr.write(
            "decisions.mcp_server requires the `mcp` SDK. Install it with "
            "`pip install mcp` (or add to pyproject and `uv sync`). The "
            "submission callables (submit_research_plan / submit_trader_proposal / "
            "submit_portfolio_decision) are still importable directly from "
            "`tradingagents.decisions` for unit-test and Phase 1 use.\n"
        )
        sys.exit(2)
    server.run()


if __name__ == "__main__":
    main()
