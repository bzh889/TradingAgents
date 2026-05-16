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
import shutil

from .types import ExecutorError


def raise_if_no_structured_output(
    stdout_text: str,
    stderr_text: str,
    executor_name: str,
    node_name: str,
    terminal_event: dict,
    submit_calls: list,
) -> None:
    """If the parser found NOTHING usable in stdout, surface stdout+stderr.

    Dogfood found that CLI tools sometimes print human-readable error
    messages (auth prompts, trust-directory rejections) on stdout / stderr
    as PLAIN TEXT, not JSON. The per-line json.loads in the parser silently
    skips them, leaving terminal_event empty — the executor would otherwise
    return NodeResult(state_delta={"market_report": ""}) and hide the real
    failure. This helper surfaces the failure.

    Call AFTER terminal_event extraction; only raises when EVERY structured
    channel (terminal_event with usable result, submit_calls) is empty.
    """
    has_result = bool(terminal_event.get("result"))
    has_submit = bool(submit_calls)
    if has_result or has_submit:
        return

    combined = "\n".join(s for s in (stdout_text.strip(), stderr_text.strip()) if s)
    if not combined:
        return  # Both empty — let the caller's NodeResult be empty (rare).

    raise ExecutorError(
        reason=categorise_failure(combined),
        node=node_name,
        raw_error=(
            f"{executor_name} subprocess produced no structured output. "
            f"stdout/stderr: {combined[:500]}"
        ),
    )


def resolve_cli_binary(name: str, executor_name: str) -> str:
    """Resolve a CLI command name to a full executable path.

    Windows-safe: npm-installed CLIs ship as `<name>` (POSIX shell script)
    + `<name>.cmd` + `<name>.ps1`. Python's subprocess.Popen with shell=False
    does NOT traverse PATHEXT on Windows, so `subprocess.Popen(["codex", ...])`
    raises FileNotFoundError even when `codex.cmd` is on PATH. shutil.which()
    DOES traverse PATHEXT and picks the first executable variant.

    Raises ExecutorError(reason="cli_not_found") if the binary cannot be found.
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise ExecutorError(
            reason="cli_not_found",
            node="",
            raw_error=(
                f"{executor_name} executor requires '{name}' in PATH. "
                f"Tried shutil.which('{name}') and got None. "
                f"Install the CLI or fix PATH and retry."
            ),
        )
    return resolved


def utf8_env(strip_vars: tuple[str, ...] = ()) -> dict[str, str]:
    """Return a copy of os.environ forced to utf-8, optionally stripping vars.

    `strip_vars` removes specific env vars before handing the env block to
    the subprocess. Each CLI executor passes the var names that would force
    the subscription CLI to fall back to pay-per-token mode:

    - claude-code → strip ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN (otherwise
      Claude Code CLI prefers the env key over keychain OAuth and the user's
      subscription stops being used)
    - codex → strip OPENAI_API_KEY / CODEX_API_KEY
    - gemini → strip GEMINI_API_KEY / GOOGLE_API_KEY (when the user wants
      the subscription/login path rather than the API-key path)

    Design §R5 / §7.1.
    """
    env = dict(os.environ)
    for var in strip_vars:
        env.pop(var, None)
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
    re.compile(r"\binvalid api key", re.IGNORECASE),
    re.compile(r"\bset (?:an )?auth method", re.IGNORECASE),
    re.compile(r"\bfix external api key", re.IGNORECASE),
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


def _ai_messages(text: str) -> list:
    """Wrap text into [AIMessage(content=text)] (empty list if text is falsy).

    Lazy-imported because importing langchain_core at module load time would
    re-introduce the 'OpenAI API key required at import' chain that
    dogfood-fix #2 worked around (TradingAgentsGraph init builds LLM clients).
    """
    if not text:
        return []
    from langchain_core.messages import AIMessage
    return [AIMessage(content=text)]


def build_state_delta(agent_role: str, text: str, state: dict) -> dict:
    """Map free-text LLM output to the exact state-delta shape each LangGraph
    node would have returned in API mode.

    Conditional edges (conditional_logic.should_continue_debate /
    should_continue_risk_analysis) route based on:
      - `state["investment_debate_state"]["current_response"]` (startswith
        "Bull" / "Bear")
      - `state["risk_debate_state"]["latest_speaker"]` (startswith
        "Aggressive" / "Conservative")
      - `state["investment_debate_state"]["count"]` (round limit)
      - `state["risk_debate_state"]["count"]` (round limit)

    Dogfood found: CLI executors returned only `{role_report: text}` which left
    these dict keys stale, so conditional fell through to the default branch
    (e.g. "Bull Researcher" returned from itself) and langgraph raised
    KeyError on the routing map lookup. This adapter reproduces the per-role
    shape so graph routing matches API mode.
    """
    messages = _ai_messages(text)
    base = {"messages": messages} if messages else {}

    # Analyst nodes — flat report key.
    if agent_role == "market_analyst":
        return {**base, "market_report": text}
    if agent_role == "social_media_analyst":
        return {**base, "sentiment_report": text}
    if agent_role == "news_analyst":
        return {**base, "news_report": text}
    if agent_role == "fundamentals_analyst":
        return {**base, "fundamentals_report": text}

    # Debate (research) nodes — must update investment_debate_state shape +
    # current_response prefix so conditional_logic startswith() check routes.
    if agent_role == "bull_researcher":
        ids = state.get("investment_debate_state", {}) or {}
        argument = f"Bull Analyst: {text}"
        new_ids = {
            "history": (ids.get("history") or "") + "\n" + argument,
            "bull_history": (ids.get("bull_history") or "") + "\n" + argument,
            "bear_history": ids.get("bear_history", ""),
            "current_response": argument,
            "count": (ids.get("count") or 0) + 1,
        }
        return {**base, "investment_debate_state": new_ids}

    if agent_role == "bear_researcher":
        ids = state.get("investment_debate_state", {}) or {}
        argument = f"Bear Analyst: {text}"
        new_ids = {
            "history": (ids.get("history") or "") + "\n" + argument,
            "bear_history": (ids.get("bear_history") or "") + "\n" + argument,
            "bull_history": ids.get("bull_history", ""),
            "current_response": argument,
            "count": (ids.get("count") or 0) + 1,
        }
        return {**base, "investment_debate_state": new_ids}

    if agent_role == "research_manager":
        ids = state.get("investment_debate_state", {}) or {}
        new_ids = {
            "judge_decision": text,
            "history": ids.get("history", ""),
            "bull_history": ids.get("bull_history", ""),
            "bear_history": ids.get("bear_history", ""),
            "current_response": text,
            "count": ids.get("count", 0),
        }
        return {
            **base,
            "investment_debate_state": new_ids,
            "investment_plan": text,
        }

    if agent_role == "trader":
        return {**base, "trader_investment_plan": text}

    # Risk debate nodes — must update risk_debate_state with latest_speaker
    # so should_continue_risk_analysis routes; conservative/neutral debators
    # follow the same shape.
    if agent_role == "aggressive_analyst":
        rds = state.get("risk_debate_state", {}) or {}
        argument = f"Aggressive Analyst: {text}"
        new_rds = {
            "history": (rds.get("history") or "") + "\n" + argument,
            "aggressive_history": (rds.get("aggressive_history") or "") + "\n" + argument,
            "conservative_history": rds.get("conservative_history", ""),
            "neutral_history": rds.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": rds.get("current_conservative_response", ""),
            "current_neutral_response": rds.get("current_neutral_response", ""),
            "count": (rds.get("count") or 0) + 1,
        }
        return {**base, "risk_debate_state": new_rds}

    if agent_role == "conservative_analyst":
        rds = state.get("risk_debate_state", {}) or {}
        argument = f"Conservative Analyst: {text}"
        new_rds = {
            "history": (rds.get("history") or "") + "\n" + argument,
            "aggressive_history": rds.get("aggressive_history", ""),
            "conservative_history": (rds.get("conservative_history") or "") + "\n" + argument,
            "neutral_history": rds.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": rds.get("current_aggressive_response", ""),
            "current_conservative_response": argument,
            "current_neutral_response": rds.get("current_neutral_response", ""),
            "count": (rds.get("count") or 0) + 1,
        }
        return {**base, "risk_debate_state": new_rds}

    if agent_role == "neutral_analyst":
        rds = state.get("risk_debate_state", {}) or {}
        argument = f"Neutral Analyst: {text}"
        new_rds = {
            "history": (rds.get("history") or "") + "\n" + argument,
            "aggressive_history": rds.get("aggressive_history", ""),
            "conservative_history": rds.get("conservative_history", ""),
            "neutral_history": (rds.get("neutral_history") or "") + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": rds.get("current_aggressive_response", ""),
            "current_conservative_response": rds.get("current_conservative_response", ""),
            "current_neutral_response": argument,
            "count": (rds.get("count") or 0) + 1,
        }
        return {**base, "risk_debate_state": new_rds}

    if agent_role == "portfolio_manager":
        rds = state.get("risk_debate_state", {}) or {}
        new_rds = {
            "judge_decision": text,
            "history": rds.get("history", ""),
            "aggressive_history": rds.get("aggressive_history", ""),
            "conservative_history": rds.get("conservative_history", ""),
            "neutral_history": rds.get("neutral_history", ""),
            "latest_speaker": "Judge",
            "current_aggressive_response": rds.get("current_aggressive_response", ""),
            "current_conservative_response": rds.get("current_conservative_response", ""),
            "current_neutral_response": rds.get("current_neutral_response", ""),
            "count": rds.get("count", 0),
        }
        return {
            **base,
            "risk_debate_state": new_rds,
            "final_trade_decision": text,
        }

    # Fallback: unknown agent role -> flat report key matching AGENT_TO_STATE_KEY.
    fallback_key = AGENT_TO_STATE_KEY.get(agent_role, f"{agent_role}_report")
    return {**base, fallback_key: text}
