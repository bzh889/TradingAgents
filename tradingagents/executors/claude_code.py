"""ClaudeCodeExecutor — runs a graph node by spawning a `claude --print` subprocess.

Phase 4 of cli-llm-rearch. The executor is the first CLI-backed NodeExecutor
implementation; Codex and Gemini (phase 5) follow the same pattern via
ProviderSpawner-style adapters but the details are intentionally not shared
(per design §3.2 — each CLI's autonomy, permission, and output model is
different).

Key decisions (anchored in CLAUDE_CODE_NESTING_NOTES.md smoke test):

- Do NOT pass `--bare` — that loses keychain OAuth, forcing the user to
  burn ANTHROPIC_API_KEY tokens and defeating the subscription cost model.
- Spawn from `tempfile.TemporaryDirectory()` so parent `CLAUDE.md` does NOT
  auto-load (saves ~46k context tokens per call).
- Use `--output-format stream-json` so we can pick out `submit_*` MCP tool
  calls (decisions schema) in real time, not only the trailing prose result.
- Full utf-8 env block (PYTHONUTF8 / PYTHONIOENCODING / LANG / LC_ALL +
  NO_COLOR + TERM=dumb) — Windows + Chinese locale would otherwise corrupt
  the pipe.
- Exit code is misleading: success and `is_error=true` both return 0.
  We inspect parsed JSON `is_error` instead.
- Fail-closed: ANY failure surface (quota, timeout, parse, is_error) raises
  ExecutorError. No retries, no executor fallback. LangGraph checkpoint
  preserves state at the failing node; the user resumes with
  `tradingagents analyze --resume --executor api` (or another CLI).

See openspec/changes/cli-llm-rearch/design.md §D1 / §D3 / §D7 / §D9 /
§Risks §R5 (encoding) and §R7 (nesting Q1 answered).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import Any, Optional

from ._subprocess_common import raise_if_no_structured_output, resolve_cli_binary, utf8_env
from .types import ExecutorError, NodeResult, NodeSpec


# Env vars that, if present, force Claude Code CLI to fall back to API-key
# pay-per-token mode and bypass the user's subscription keychain OAuth.
# Stripped from the subprocess env block in run_node(). Dogfood-found:
# a stray ANTHROPIC_API_KEY=sk-... in the parent process (even a dummy one
# set elsewhere) bypassed the subscription and made the run fail with
# "Invalid API key" instead of using the logged-in account.
_SUBSCRIPTION_KILLING_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
)


# Quota / rate-limit / auth-failure detection patterns. Subscription CLIs do
# not return structured error codes for these; we sniff the result text.
_QUOTA_PATTERNS = (
    re.compile(r"\brate limit", re.IGNORECASE),
    re.compile(r"\bquota", re.IGNORECASE),
    re.compile(r"\busage limit", re.IGNORECASE),
    re.compile(r"\b429\b"),  # HTTP 429
    re.compile(r"\btry again in \d+ seconds", re.IGNORECASE),
)

_AUTH_PATTERNS = (
    re.compile(r"\bnot logged in", re.IGNORECASE),
    re.compile(r"\bplease run /login", re.IGNORECASE),
    re.compile(r"\bauthentication", re.IGNORECASE),
    re.compile(r"\b401\b"),  # HTTP 401
)


def _utf8_env() -> dict[str, str]:
    """Return a copy of os.environ with utf-8 forced AND subscription-killing
    env vars stripped. Design §R5 / §7.1 + dogfood fix.
    """
    return utf8_env(strip_vars=_SUBSCRIPTION_KILLING_VARS)


def _categorise_failure(result_text: str) -> str:
    """Map an is_error=true result string to an ExecutorError.reason value."""
    for pat in _AUTH_PATTERNS:
        if pat.search(result_text):
            return "auth_failed"
    for pat in _QUOTA_PATTERNS:
        if pat.search(result_text):
            return "quota_exhausted"
    return "claude_code_error"


def _build_prompt(node_name: str, state: dict, spec: NodeSpec) -> str:
    """Build the prompt string passed as positional arg to `claude --print`.

    The prompt embeds the agent role + a serialised view of the relevant
    state keys, plus an explicit instruction to submit decisions via the
    decisions MCP tools when applicable. Phase 4 sticks to a small, generic
    template; phase 5 / per-agent tuning happens in tasks.md follow-ups.
    """
    role = spec.agent_role or node_name
    state_blob = json.dumps(
        {k: v for k, v in state.items() if isinstance(v, (str, int, float, bool, type(None)))},
        ensure_ascii=False,
    )
    prompt_body = spec.prompt_template or (
        f"You are the {role}. Run your analysis and return the result. "
        f"If you need market data, call MCP tools from `tradingagents-dataflows`. "
        f"If your role produces a structured decision, call the matching tool from "
        f"`tradingagents-decisions` (submit_research_plan / submit_trader_proposal / "
        f"submit_portfolio_decision)."
    )
    return (
        f"[node: {node_name}]\n"
        f"[role: {role}]\n"
        f"[state-keys: {state_blob}]\n\n"
        f"{prompt_body}"
    )


def _parse_stream(stdout_text: str) -> tuple[list[dict], dict]:
    """Parse a stream-json or single-json blob into (tool_calls, result_event).

    Returns the list of `submit_*` tool call payloads (in order) plus the
    terminal result event. If only one JSON object is present (--output-format
    json mode), `tool_calls` is empty and `result_event` is that object.
    """
    tool_calls: list[dict] = []
    result_event: dict = {}

    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")
        if etype == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "tool_use":
                tool_name = item.get("name", "")
                if tool_name.startswith("submit_"):
                    tool_calls.append({
                        "name": tool_name,
                        "input": item.get("input", {}),
                    })
        elif etype == "result":
            result_event = event

    return tool_calls, result_event


def _structured_state_delta(tool_calls: list[dict], node_name: str) -> Optional[dict]:
    """Project the latest decisions MCP submission into the right state key."""
    if not tool_calls:
        return None

    # Pick the last submit_* call — the agent may have iterated.
    last = tool_calls[-1]
    tool_name = last["name"]
    payload = last["input"]

    key_map = {
        "submit_research_plan": "investment_plan",
        "submit_trader_proposal": "trader_investment_plan",
        "submit_portfolio_decision": "final_trade_decision",
    }
    state_key = key_map.get(tool_name)
    if state_key is None:
        return None
    return {state_key: payload, "portfolio_decision": payload} if tool_name == "submit_portfolio_decision" else {state_key: payload}


# Map agent_role -> state key for free-text fallback path. Mirrors LangGraph
# node return values when an agent does NOT call a structured submit tool.
_AGENT_TO_STATE_KEY = {
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


class ClaudeCodeExecutor:
    """NodeExecutor backed by `claude --print` subprocess."""

    name: str = "claude-code"

    def __init__(
        self,
        # 60s was the original default; dogfood-found-bug: a real
        # market_analyst node takes 60-180s end-to-end (fetch data + reason +
        # write report), and 60s timed out before the subprocess could even
        # finish producing output. 300s is a safer default; the user can
        # override via TradingAgentsGraph(executor=instance(timeout_seconds=N))
        # if needed.
        timeout_seconds: int = 300,
        mcp_config: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.mcp_config = mcp_config  # Path to MCP config JSON; phase 4b wires this
        self.extra_args = list(extra_args) if extra_args else []

    def supports_structured(self) -> bool:
        return True

    def run_node(
        self,
        node_name: str,
        state: dict[str, Any],
        spec: NodeSpec,
    ) -> NodeResult:
        prompt = _build_prompt(node_name, state, spec)
        argv = self._build_argv(prompt)
        env = _utf8_env()

        # Spawn from a clean temp dir so parent CLAUDE.md does NOT auto-load.
        with tempfile.TemporaryDirectory(prefix="tradingagents-claude-") as tmpdir:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=tmpdir,
                text=False,
            )

            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise ExecutorError(
                    reason="timeout",
                    node=node_name,
                    raw_error=f"claude-code subprocess exceeded {self.timeout_seconds}s",
                )

        stdout_text = (
            stdout_bytes.decode("utf-8", errors="replace")
            if isinstance(stdout_bytes, (bytes, bytearray))
            else str(stdout_bytes)
        )
        stderr_text = (
            stderr_bytes.decode("utf-8", errors="replace")
            if isinstance(stderr_bytes, (bytes, bytearray))
            else str(stderr_bytes)
        )

        tool_calls, result_event = _parse_stream(stdout_text)

        # Defensive: if claude printed a plain-text error (e.g. argv mismatch)
        # before any JSON event, surface it.
        raise_if_no_structured_output(
            stdout_text, stderr_text, "claude-code", node_name, result_event, tool_calls
        )

        # Failure detection: exit code is unreliable; check is_error from JSON.
        if result_event.get("is_error"):
            result_text = result_event.get("result", "")
            raise ExecutorError(
                reason=_categorise_failure(result_text),
                node=node_name,
                raw_error=result_text or stderr_text,
            )

        # Structured path: an MCP submit_* tool call became the decision.
        structured_delta = _structured_state_delta(tool_calls, node_name)
        if structured_delta is not None:
            return NodeResult(
                state_delta=structured_delta,
                raw_artifact_path=None,
                executor_metadata={
                    "executor": "claude-code",
                    "agent_role": spec.agent_role,
                    "structured": True,
                    "session_id": result_event.get("session_id"),
                    "cost_usd": result_event.get("total_cost_usd"),
                },
            )

        # Free-text path: surface the result string under the agent's state key.
        text = result_event.get("result", "")
        state_key = _AGENT_TO_STATE_KEY.get(spec.agent_role, f"{spec.agent_role}_report")
        # Dogfood-found-bug: langgraph's add_messages reducer wraps raw strings
        # into HumanMessage, which has no `tool_calls` attribute. The graph's
        # conditional edges read `.tool_calls` on the last message and crash.
        # Wrap in AIMessage so the downstream contract matches API-mode nodes.
        from langchain_core.messages import AIMessage
        messages = [AIMessage(content=text)] if text else []
        return NodeResult(
            state_delta={state_key: text, "messages": messages},
            raw_artifact_path=None,
            executor_metadata={
                "executor": "claude-code",
                "agent_role": spec.agent_role,
                "structured": False,
                "session_id": result_event.get("session_id"),
                "cost_usd": result_event.get("total_cost_usd"),
            },
        )

    def _build_argv(self, prompt: str) -> list[str]:
        # `stream-json` output format requires `--verbose` per Claude Code 2.1.x
        # ("When using --print, --output-format=stream-json requires --verbose").
        # The verbose flag toggles per-event JSON emission; without it the
        # subprocess errors out and exits 0 with no parsed events.
        binary = resolve_cli_binary("claude", executor_name="claude-code")
        argv = [
            binary,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
        ]
        if self.mcp_config:
            argv.extend(["--mcp-config", self.mcp_config, "--strict-mcp-config"])
        argv.extend(self.extra_args)
        argv.append(prompt)
        return argv
