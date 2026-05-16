"""Decisions: schema-validated submission API for CLI executors.

Each `submit_*` function accepts kwargs matching the corresponding Pydantic
schema in `tradingagents.agents.schemas`, runs Pydantic validation, and
returns the validated instance. Used by CLI executors (claude-code / codex /
gemini) to receive structured output via MCP tool calls without parsing
markdown stdout. API mode uses langchain `bind_structured` directly and does
not call these functions.

See openspec/changes/cli-llm-rearch/design.md §D3 / §D10.
"""

from tradingagents.agents.schemas import (
    PortfolioDecision,
    ResearchPlan,
    TraderProposal,
)


def submit_research_plan(**kwargs) -> ResearchPlan:
    return ResearchPlan(**kwargs)


def submit_trader_proposal(**kwargs) -> TraderProposal:
    return TraderProposal(**kwargs)


def submit_portfolio_decision(**kwargs) -> PortfolioDecision:
    return PortfolioDecision(**kwargs)


__all__ = [
    "submit_research_plan",
    "submit_trader_proposal",
    "submit_portfolio_decision",
]
