"""Phase 2 / task 2.5 — decisions submission API contract.

Tests the Python-level submission functions that the decisions MCP server
wraps. Validation logic lives in `tradingagents.agents.schemas` (existing
Pydantic schemas); these tests confirm the submission wrappers don't
re-implement validation and surface Pydantic errors faithfully.
"""

import pytest
from pydantic import ValidationError


@pytest.mark.unit
class TestDecisionsModuleExports:
    def test_can_import_decisions(self):
        import tradingagents.decisions  # noqa: F401

    def test_top_level_exports(self):
        from tradingagents import decisions

        for name in (
            "submit_research_plan",
            "submit_trader_proposal",
            "submit_portfolio_decision",
        ):
            assert hasattr(decisions, name), f"decisions module 缺 {name}"


@pytest.mark.unit
class TestSubmitResearchPlan:
    def test_happy_path_returns_research_plan(self):
        from tradingagents.agents.schemas import PortfolioRating, ResearchPlan
        from tradingagents.decisions import submit_research_plan

        result = submit_research_plan(
            recommendation="Buy",
            rationale="Strong bull case from market analyst.",
            strategic_actions="Accumulate 5% position over 3 days.",
        )
        assert isinstance(result, ResearchPlan)
        assert result.recommendation == PortfolioRating.BUY
        assert "5%" in result.strategic_actions

    def test_rejects_invalid_recommendation(self):
        from tradingagents.decisions import submit_research_plan

        with pytest.raises(ValidationError):
            submit_research_plan(
                recommendation="StrongBuy",  # not a PortfolioRating
                rationale="...",
                strategic_actions="...",
            )

    def test_rejects_missing_required_field(self):
        from tradingagents.decisions import submit_research_plan

        with pytest.raises(ValidationError):
            submit_research_plan(recommendation="Buy")  # missing rationale + actions


@pytest.mark.unit
class TestSubmitTraderProposal:
    def test_happy_path_minimal_fields(self):
        from tradingagents.agents.schemas import TraderAction, TraderProposal
        from tradingagents.decisions import submit_trader_proposal

        result = submit_trader_proposal(
            action="Buy",
            reasoning="Aligns with bull research and confirmed momentum.",
        )
        assert isinstance(result, TraderProposal)
        assert result.action == TraderAction.BUY
        # Optional fields default to None
        assert result.entry_price is None
        assert result.stop_loss is None

    def test_happy_path_full_fields(self):
        from tradingagents.decisions import submit_trader_proposal

        result = submit_trader_proposal(
            action="Sell",
            reasoning="Risk debate flagged downside.",
            entry_price=412.50,
            stop_loss=420.00,
            position_sizing="3% of portfolio",
        )
        assert result.entry_price == 412.50
        assert result.position_sizing == "3% of portfolio"

    def test_rejects_invalid_action(self):
        from tradingagents.decisions import submit_trader_proposal

        with pytest.raises(ValidationError):
            submit_trader_proposal(action="MaybeBuy", reasoning="...")

    def test_rejects_overweight_in_trader_action(self):
        """Trader uses 3-tier action (Buy/Hold/Sell), NOT 5-tier rating.
        Overweight is a valid PortfolioRating but invalid TraderAction —
        this test locks that boundary."""
        from tradingagents.decisions import submit_trader_proposal

        with pytest.raises(ValidationError):
            submit_trader_proposal(action="Overweight", reasoning="...")


@pytest.mark.unit
class TestSubmitPortfolioDecision:
    def test_happy_path_minimal(self):
        from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating
        from tradingagents.decisions import submit_portfolio_decision

        result = submit_portfolio_decision(
            rating="Overweight",
            executive_summary="Take 7% position over 5 trading days.",
            investment_thesis="Strong fundamentals + favorable technicals.",
        )
        assert isinstance(result, PortfolioDecision)
        assert result.rating == PortfolioRating.OVERWEIGHT

    def test_happy_path_with_optional_fields(self):
        from tradingagents.decisions import submit_portfolio_decision

        result = submit_portfolio_decision(
            rating="Buy",
            executive_summary="Entry at 410, target 450.",
            investment_thesis="Q3 earnings + index inclusion.",
            price_target=450.00,
            time_horizon="3-6 months",
        )
        assert result.price_target == 450.00
        assert result.time_horizon == "3-6 months"

    def test_rejects_invalid_rating(self):
        from tradingagents.decisions import submit_portfolio_decision

        with pytest.raises(ValidationError):
            submit_portfolio_decision(
                rating="StrongBuy",
                executive_summary="...",
                investment_thesis="...",
            )

    def test_rejects_missing_thesis(self):
        from tradingagents.decisions import submit_portfolio_decision

        with pytest.raises(ValidationError):
            submit_portfolio_decision(
                rating="Buy",
                executive_summary="Only summary, no thesis.",
            )


@pytest.mark.unit
class TestMCPServerModuleExists:
    """Phase 2 task 2.4 — mcp_server module importable; actual MCP transport
    wiring may lazily depend on the `mcp` SDK and is exercised in phase 4."""

    def test_can_import_mcp_server_module(self):
        import tradingagents.decisions.mcp_server  # noqa: F401

    def test_mcp_server_module_exposes_tool_handlers(self):
        """The server module SHALL expose the same 3 submission callables that
        the Python API offers, regardless of whether the `mcp` SDK is wired."""
        from tradingagents.decisions import mcp_server

        for name in (
            "submit_research_plan",
            "submit_trader_proposal",
            "submit_portfolio_decision",
        ):
            assert hasattr(mcp_server, name), f"mcp_server 缺 {name}"
