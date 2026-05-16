"""Public re-exports from the agents package — lazily loaded.

The eager re-imports below tank cold-start time for anything that just needs
`tradingagents.agents.schemas` (e.g. the decisions MCP server, which Claude
Code probes for tools immediately after spawn). Each agent module pulls in a
slice of langchain; the cumulative load is ~20-30s on a cold venv.

PEP 562 `__getattr__` resolves each name on first access via importlib, then
caches it back into module globals so subsequent accesses are direct. The
public surface is unchanged — `from tradingagents.agents import
create_market_analyst` still works.
"""

import importlib


_LAZY_BINDINGS = {
    "AgentState": ("tradingagents.agents.utils.agent_states", "AgentState"),
    "InvestDebateState": ("tradingagents.agents.utils.agent_states", "InvestDebateState"),
    "RiskDebateState": ("tradingagents.agents.utils.agent_states", "RiskDebateState"),
    "create_msg_delete": ("tradingagents.agents.utils.agent_utils", "create_msg_delete"),
    "create_fundamentals_analyst": ("tradingagents.agents.analysts.fundamentals_analyst", "create_fundamentals_analyst"),
    "create_market_analyst": ("tradingagents.agents.analysts.market_analyst", "create_market_analyst"),
    "create_news_analyst": ("tradingagents.agents.analysts.news_analyst", "create_news_analyst"),
    "create_social_media_analyst": ("tradingagents.agents.analysts.social_media_analyst", "create_social_media_analyst"),
    "create_bear_researcher": ("tradingagents.agents.researchers.bear_researcher", "create_bear_researcher"),
    "create_bull_researcher": ("tradingagents.agents.researchers.bull_researcher", "create_bull_researcher"),
    "create_aggressive_debator": ("tradingagents.agents.risk_mgmt.aggressive_debator", "create_aggressive_debator"),
    "create_conservative_debator": ("tradingagents.agents.risk_mgmt.conservative_debator", "create_conservative_debator"),
    "create_neutral_debator": ("tradingagents.agents.risk_mgmt.neutral_debator", "create_neutral_debator"),
    "create_research_manager": ("tradingagents.agents.managers.research_manager", "create_research_manager"),
    "create_portfolio_manager": ("tradingagents.agents.managers.portfolio_manager", "create_portfolio_manager"),
    "create_trader": ("tradingagents.agents.trader.trader", "create_trader"),
}


def __getattr__(name):
    if name in _LAZY_BINDINGS:
        module_path, attr = _LAZY_BINDINGS[name]
        mod = importlib.import_module(module_path)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'tradingagents.agents' has no attribute {name!r}")


__all__ = list(_LAZY_BINDINGS.keys())
