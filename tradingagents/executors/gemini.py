"""GeminiExecutor — runs a graph node by spawning a `gemini -p` subprocess.

Mirrors the other CLI executors (subprocess.Popen + utf-8 env + temp cwd +
JSON parsing + fail-closed). Gemini argv differs:

    gemini -p "<prompt>" -o stream-json -y --skip-trust [--allowed-mcp-server-names ...]

Gemini CLI native flags:
- `-p` / `--prompt`: non-interactive prompt
- `-o stream-json`: streaming JSON events (also supports `-o json` for single)
- `-y` / `--yolo`: auto-approve tool actions (subscription users normally OK
  in non-interactive runs; the executor passes this so tool calls don't block)
- `--skip-trust`: skip workspace-trust prompt (we run from a temp dir)
- `--allowed-mcp-server-names`: explicit allowlist for MCP servers when wired
  (Phase 4b/5b configures this dynamically)

Auth: Gemini reads from its login keychain by default. Subscription users
get the no-token-cost path automatically.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Any, Optional

from ._subprocess_common import (
    AGENT_TO_STATE_KEY,
    SUBMIT_TOOL_TO_STATE_KEY,
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
        f"Use MCP tools from `tradingagents-dataflows` for market data. "
        f"Call `tradingagents-decisions` submit_* tool when your role outputs "
        f"a structured decision."
    )
    return (
        f"[node: {node_name}]\n"
        f"[role: {role}]\n"
        f"[state-keys: {state_blob}]\n\n"
        f"{prompt_body}"
    )


def _parse_gemini_stream(stdout_text: str) -> tuple[list[dict], dict]:
    """Parse Gemini CLI JSON output into (submit_calls, terminal_event).

    Gemini's output_format=stream-json emits events:
    - tool_call / function_call: tool invocation
    - text / message: model response chunks
    - usage: token counts
    - error: failures

    Single-shot output_format=json returns one object with `response` /
    `text` field plus optional `tool_calls`.
    """
    submit_calls: list[dict] = []
    terminal_event: dict = {}
    accumulated_text = ""

    # Try single-JSON first (output_format=json).
    stripped = stdout_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            obj = json.loads(stripped)
            # Error envelope: {"type": "error", "message": ...} OR {"error": "..."}
            if obj.get("type") == "error" or obj.get("error"):
                return [], {
                    "is_error": True,
                    "result": obj.get("message") or obj.get("error") or json.dumps(obj),
                }
            # Normal single-JSON: pull tool_calls and response
            for call in obj.get("tool_calls", []) or []:
                name = call.get("name", "")
                if name.startswith("submit_"):
                    submit_calls.append({"name": name, "input": call.get("arguments", call.get("input", {}))})
            terminal_event = {
                "result": obj.get("response") or obj.get("text") or obj.get("content", ""),
                "is_error": False,
                "usage": obj.get("usage", {}),
            }
            return submit_calls, terminal_event
        except json.JSONDecodeError:
            pass  # Fall through to stream-json parsing

    # Stream-json
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype in ("tool_call", "function_call"):
            name = event.get("name", "") or event.get("tool", "")
            if name.startswith("submit_"):
                args = event.get("arguments") or event.get("input") or {}
                submit_calls.append({"name": name, "input": args})
        elif etype in ("text", "message", "agent_message"):
            text_chunk = event.get("text") or event.get("content") or ""
            accumulated_text += text_chunk
        elif etype == "error":
            terminal_event = {
                "is_error": True,
                "result": event.get("message", "") or json.dumps(event),
            }
        elif etype in ("done", "complete", "turn_completed"):
            terminal_event.setdefault("usage", event.get("usage", {}))

    if not terminal_event:
        terminal_event = {"is_error": False, "result": accumulated_text}
    elif "result" not in terminal_event and accumulated_text:
        terminal_event["result"] = accumulated_text

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


class GeminiExecutor:
    """NodeExecutor backed by `gemini -p` subprocess."""

    name: str = "gemini"

    def __init__(
        self,
        timeout_seconds: int = 60,
        model: Optional[str] = None,
        allowed_mcp_servers: Optional[list[str]] = None,
        extra_args: Optional[list[str]] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.allowed_mcp_servers = list(allowed_mcp_servers) if allowed_mcp_servers else []
        self.extra_args = list(extra_args) if extra_args else []

    def supports_structured(self) -> bool:
        # When Gemini CLI exposes MCP, structured path works. Without MCP,
        # fall back is prompt+JSON parse (still capable but more fragile).
        return True

    def run_node(
        self,
        node_name: str,
        state: dict[str, Any],
        spec: NodeSpec,
    ) -> NodeResult:
        prompt = _build_prompt(node_name, state, spec)
        argv = self._build_argv(prompt)
        env = utf8_env()

        with tempfile.TemporaryDirectory(prefix="tradingagents-gemini-") as tmpdir:
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
                    raw_error=f"gemini subprocess exceeded {self.timeout_seconds}s",
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

        submit_calls, terminal = _parse_gemini_stream(stdout_text)

        if terminal.get("is_error"):
            result_text = terminal.get("result", "") or stderr_text
            raise ExecutorError(
                reason=categorise_failure(result_text),
                node=node_name,
                raw_error=result_text,
            )

        # Defensive: surface auth/setup errors that the CLI prints as plain text.
        raise_if_no_structured_output(
            stdout_text, stderr_text, "gemini", node_name, terminal, submit_calls
        )

        structured_delta = _structured_state_delta(submit_calls)
        if structured_delta is not None:
            return NodeResult(
                state_delta=structured_delta,
                raw_artifact_path=None,
                executor_metadata={
                    "executor": "gemini",
                    "agent_role": spec.agent_role,
                    "structured": True,
                    "usage": terminal.get("usage", {}),
                },
            )

        text = terminal.get("result", "")
        state_key = AGENT_TO_STATE_KEY.get(spec.agent_role, f"{spec.agent_role}_report")
        return NodeResult(
            state_delta={state_key: text, "messages": [text] if text else []},
            raw_artifact_path=None,
            executor_metadata={
                "executor": "gemini",
                "agent_role": spec.agent_role,
                "structured": False,
                "usage": terminal.get("usage", {}),
            },
        )

    def _build_argv(self, prompt: str) -> list[str]:
        binary = resolve_cli_binary("gemini", executor_name="gemini")
        argv = [binary, "-p", prompt, "-o", "stream-json", "-y", "--skip-trust"]
        if self.model:
            argv.extend(["-m", self.model])
        if self.allowed_mcp_servers:
            argv.append("--allowed-mcp-server-names")
            argv.extend(self.allowed_mcp_servers)
        argv.extend(self.extra_args)
        return argv
