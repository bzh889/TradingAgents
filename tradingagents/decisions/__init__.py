"""Decisions: schema-validated submission API for CLI executors.

Each `submit_*` function accepts kwargs matching the corresponding Pydantic
schema in `tradingagents.agents.schemas`, runs Pydantic validation, and
returns the validated instance. Used by CLI executors (claude-code / codex /
gemini) to receive structured output via MCP tool calls without parsing
markdown stdout. API mode uses langchain `bind_structured` directly and does
not call these functions.

Dogfood-found: importing `tradingagents.agents.schemas` at module load
triggers `tradingagents.agents.__init__` which pulls in every agent (all of
langchain). That tanked MCP-server cold-start time to ~30s and made Claude
Code give up before tools were discovered. Lazy-import the schemas inside
each submit_* so this package is near-instant to load.

See openspec/changes/cli-llm-rearch/design.md §D3 / §D10.
"""


def submit_research_plan(**kwargs):
    from tradingagents.agents.schemas import ResearchPlan

    return ResearchPlan(**kwargs)


def submit_trader_proposal(**kwargs):
    from tradingagents.agents.schemas import TraderProposal

    return TraderProposal(**kwargs)


def submit_portfolio_decision(**kwargs):
    from tradingagents.agents.schemas import PortfolioDecision

    return PortfolioDecision(**kwargs)


__all__ = [
    "submit_research_plan",
    "submit_trader_proposal",
    "submit_portfolio_decision",
]
