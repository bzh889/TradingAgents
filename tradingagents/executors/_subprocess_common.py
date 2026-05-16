"""Shared helpers for CLI subprocess executors (claude-code / codex / gemini).

Each CLI has its own argv structure, output event names, and quirks (see
each executor's module). What they all share:

- The utf-8 environment block required to keep Windows + non-ASCII pipes alive
- A regex sweep of result text for quota / rate-limit / auth-failure signals
- A mapping from LangGraph agent_role to the state key the node should populate
  when there is no structured (MCP tool call) submission

The intentional non-shared pieces are argv construction, stream-event parsing,
and MCP wiring — those are CLI-specific and live in each executor file.
"""

from __future__ import annotations

import os
import re


def utf8_env() -> dict[str, str]:
    """Return a copy of os.environ forced to utf-8. Design §R5 / §7.1."""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return env


# Each pattern is case-insensitive (set via re.IGNORECASE).
QUOTA_PATTERNS = (
    re.compile(r"\brate limit", re.IGNORECASE),
    re.compile(r"\bquota", re.IGNORECASE),
    re.compile(r"\busage limit", re.IGNORECASE),
    re.compile(r"\b429\b"),
    re.compile(r"\btry again in \d+ seconds", re.IGNORECASE),
    re.compile(r"\btoo many requests", re.IGNORECASE),
)

AUTH_PATTERNS = (
    re.compile(r"\bnot logged in", re.IGNORECASE),
    re.compile(r"\bplease run /login", re.IGNORECASE),
    re.compile(r"\bauthentication", re.IGNORECASE),
    re.compile(r"\bunauthori[sz]ed", re.IGNORECASE),
    re.compile(r"\b401\b"),
)


def categorise_failure(result_text: str) -> str:
    """Map an error/failure result string to an ExecutorError.reason value.

    Auth is checked first because some auth errors mention rate-limit-like
    wording (e.g. "rate limit on auth attempts").
    """
    for pat in AUTH_PATTERNS:
        if pat.search(result_text):
            return "auth_failed"
    for pat in QUOTA_PATTERNS:
        if pat.search(result_text):
            return "quota_exhausted"
    return "executor_error"


# Map agent_role -> state key for free-text fallback (no MCP submit_* call).
# Mirrors what each LangGraph node returns from the API mode path.
AGENT_TO_STATE_KEY: dict[str, str] = {
    "market_analyst": "market_report",
    "social_media_analyst": "sentiment_report",
    "news_analyst": "news_report",
    "fundamentals_analyst": "fundamentals_report",
    "bull_researcher": "bull_history",
    "bear_researcher": "bear_history",
    "research_manager": "investment_plan",
    "trader": "trader_investment_plan",
    "aggressive_analyst": "current_aggressive_response",
    "neutral_analyst": "current_neutral_response",
    "conservative_analyst": "current_conservative_response",
    "portfolio_manager": "final_trade_decision",
}


# Map MCP submit tool name -> LangGraph state key for structured-output path.
SUBMIT_TOOL_TO_STATE_KEY: dict[str, str] = {
    "submit_research_plan": "investment_plan",
    "submit_trader_proposal": "trader_investment_plan",
    "submit_portfolio_decision": "final_trade_decision",
}
