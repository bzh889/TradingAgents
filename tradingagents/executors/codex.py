"""CodexExecutor — runs a graph node by spawning a `codex exec` subprocess.

Mirrors ClaudeCodeExecutor's shape (subprocess.Popen + utf-8 env + temp cwd
+ stream-json parsing + fail-closed). Codex argv differs:

    codex exec --json -s read-only -c 'model_reasoning_effort="medium"' "<prompt>"

Stream events use OpenAI Codex's `turn.completed` / `item.completed` shape.
`item.completed` with `item.type == "tool_use"` carries decisions MCP
submissions when Codex calls them.

Key Codex quirks (per earlier session-skill experience):
- Read-only sandbox (`-s read-only`) is the safe default — Codex can read but
  not write project files.
- Codex JSON stream sometimes embeds reasoning traces (`reasoning` items) —
  these are informational, not state-bearing.
- Codex auth: requires `codex login` or `$CODEX_API_KEY` / `$OPENAI_API_KEY`
  to be set. Subscription via ChatGPT login is the no-token-cost path.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Any, Optional

from ._subprocess_common import (
    AGENT_TO_STATE_KEY,
    SUBMIT_TOOL_TO_STATE_KEY,
    build_state_delta,
    categorise_failure,
    raise_if_no_structured_output,
    resolve_cli_binary,
    utf8_env,
)
from .types import ExecutorError, NodeResult, NodeSpec


def _build_prompt(node_name: str, state: dict, spec: NodeSpec) -> str:
    role = spec.agent_role or node_name
    state_blob = json.dumps(
        {k: v for k, v in state.items() if isinstance(v, (str, int, float, bool, type(None)))},
        ensure_ascii=False,
    )
    prompt_body = spec.prompt_template or (
        f"You are the {role}. Run your analysis. "
        f"Call MCP tools from `tradingagents-dataflows` to fetch market data. "
        f"If your role produces a structured decision, call the matching "
        f"`tradingagents-decisions` tool (submit_research_plan / "
        f"submit_trader_proposal / submit_portfolio_decision)."
    )
    return (
        f"[node: {node_name}]\n"
        f"[role: {role}]\n"
        f"[state-keys: {state_blob}]\n\n"
        f"{prompt_body}"
    )


def _parse_codex_stream(stdout_text: str) -> tuple[list[dict], dict]:
    """Parse codex --json stream into (submit_calls, terminal_event).

    Codex emits events of type:
    - thread.started: { thread_id: ... }
    - item.completed: { item: { type: "reasoning"|"tool_use"|"agent_message", ... }}
    - turn.completed: { usage: { ... } } — terminal event
    """
    submit_calls: list[dict] = []
    terminal_event: dict = {}
    last_message_text = ""
    saw_error = False
    error_text = ""

    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "item.completed":
            item = event.get("item", {})
            itype = item.get("type")
            if itype == "tool_use":
                name = item.get("name", "")
                if name.startswith("submit_"):
                    submit_calls.append(
                        {"name": name, "input": item.get("input", {})}
                    )
            elif itype == "agent_message":
                last_message_text = item.get("text", last_message_text)
        elif etype == "turn.completed":
            terminal_event = event
        elif etype == "error":
            saw_error = True
            error_text = event.get("message", "") or json.dumps(event)

    if saw_error and not terminal_event:
        terminal_event = {"type": "error", "is_error": True, "result": error_text}

    if last_message_text and "result" not in terminal_event:
        terminal_event["result"] = last_message_text

    return submit_calls, terminal_event


def _structured_state_delta(submit_calls: list[dict]) -> Optional[dict]:
    if not submit_calls:
        return None
    last = submit_calls[-1]
    state_key = SUBMIT_TOOL_TO_STATE_KEY.get(last["name"])
    if state_key is None:
        return None
    payload = last["input"]
    delta = {state_key: payload}
    if last["name"] == "submit_portfolio_decision":
        delta["portfolio_decision"] = payload
    return delta


class CodexExecutor:
    """NodeExecutor backed by `codex exec` subprocess."""

    name: str = "codex"

    def __init__(
        self,
        timeout_seconds: int = 600,
        reasoning_effort: str = "medium",
        extra_args: Optional[list[str]] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.extra_args = list(extra_args) if extra_args else []

    def supports_structured(self) -> bool:
        return True  # via MCP submit_* tools

    def run_node(
        self,
        node_name: str,
        state: dict[str, Any],
        spec: NodeSpec,
    ) -> NodeResult:
        prompt = _build_prompt(node_name, state, spec)
        argv = self._build_argv(prompt)
        env = utf8_env()

        with tempfile.TemporaryDirectory(prefix="tradingagents-codex-") as tmpdir:
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
                    raw_error=f"codex subprocess exceeded {self.timeout_seconds}s",
                )

        stdout_text = (
            stdout_bytes.decode("utf-8", errors="replace")
            if isinstance(stdout_bytes, (bytes, bytearray))
            else str(stdout_bytes or "")
        )
        stderr_text = (
            stderr_bytes.decode("utf-8", errors="replace")
            if isinstance(stderr_bytes, (bytes, bytearray))
            else str(stderr_bytes or "")
        )

        submit_calls, terminal = _parse_codex_stream(stdout_text)

        if terminal.get("is_error") or terminal.get("type") == "error":
            result_text = terminal.get("result", "") or stderr_text
            raise ExecutorError(
                reason=categorise_failure(result_text),
                node=node_name,
                raw_error=result_text,
            )

        # Defensive: if parser saw NOTHING usable but stdout/stderr have text,
        # the CLI likely emitted a human-readable error (auth, trust, etc.)
        # that did not surface as a parseable JSON event. Surface it.
        raise_if_no_structured_output(
            stdout_text, stderr_text, "codex", node_name, terminal, submit_calls
        )

        structured_delta = _structured_state_delta(submit_calls)
        if structured_delta is not None:
            return NodeResult(
                state_delta=structured_delta,
                raw_artifact_path=None,
                executor_metadata={
                    "executor": "codex",
                    "agent_role": spec.agent_role,
                    "structured": True,
                    "usage": terminal.get("usage", {}),
                },
            )

        text = terminal.get("result", "")
        delta = build_state_delta(spec.agent_role, text, state)
        return NodeResult(
            state_delta=delta,
            raw_artifact_path=None,
            executor_metadata={
                "executor": "codex",
                "agent_role": spec.agent_role,
                "structured": False,
                "usage": terminal.get("usage", {}),
            },
        )

    def _build_argv(self, prompt: str) -> list[str]:
        binary = resolve_cli_binary("codex", executor_name="codex")
        # --skip-git-repo-check: Codex refuses to run in non-git directories
        # by default. Each node spawns from a fresh tempfile.TemporaryDirectory()
        # which is never a git repo. Without this flag the subprocess exits
        # with "Not inside a trusted directory" and no JSON events.
        argv = [
            binary,
            "exec",
            "--json",
            "-s",
            "read-only",
            "--skip-git-repo-check",
            "-c",
            f'model_reasoning_effort="{self.reasoning_effort}"',
        ]
        argv.extend(self.extra_args)
        argv.append(prompt)
        return argv
