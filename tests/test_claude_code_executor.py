"""Phase 4 / task 4.13 — ClaudeCodeExecutor unit tests with mocked subprocess.

The real Claude Code CLI invocation is exercised in phase 4 verify gate
(operational test) — this file mocks `subprocess.Popen` so the assertions
focus on wiring correctness:

- Implements NodeExecutor protocol
- Spawns claude with the right argv + env (utf-8 block + clean working dir)
- Does NOT pass --bare (keychain auth required for subscription users)
- Parses stream-json events into NodeResult
- Extracts MCP submit_* tool calls into structured state_delta
- Detects quota / rate-limit / auth failure as ExecutorError
- Honours per-node timeout
- Fail-closed: raises ExecutorError without retrying
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestClaudeCodeExecutorBasics:
    def test_can_import(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor  # noqa: F401

    def test_executor_has_name(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor

        assert ClaudeCodeExecutor().name == "claude-code"

    def test_implements_node_executor_protocol(self):
        from tradingagents.executors.base import NodeExecutor
        from tradingagents.executors.claude_code import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor()
        assert hasattr(ex, "name")
        assert callable(getattr(ex, "run_node", None))
        assert callable(getattr(ex, "supports_structured", None))
        assert isinstance(ex, NodeExecutor)  # runtime_checkable

    def test_supports_structured_true(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor

        # claude-code supports structured output via MCP submit_decision tools
        assert ClaudeCodeExecutor().supports_structured() is True


@pytest.mark.unit
class TestClaudeCodeExecutorEnvironment:
    """Spawning the child must scrub locale and force utf-8 per design §7.1."""

    def _fake_completed_process(self, result_text: str = "OK", is_error: bool = False):
        """Build a fake Popen.communicate() return for stream-json output."""
        events = [
            {"type": "system", "subtype": "init"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": is_error,
                "result": result_text,
                "session_id": "fake-session",
            },
        ]
        return ("\n".join(json.dumps(e) for e in events), "")

    def test_subprocess_env_has_utf8_block(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._fake_completed_process("market report content")
            proc.returncode = 0
            mock_popen.return_value = proc

            ex = ClaudeCodeExecutor()
            ex.run_node(
                "market_analyst",
                state={"company_of_interest": "SPY"},
                spec=NodeSpec(agent_role="market_analyst", prompt_template="Analyze {company_of_interest}"),
            )

            popen_kwargs = mock_popen.call_args.kwargs
            env = popen_kwargs["env"]
            assert env["PYTHONUTF8"] == "1"
            assert env["PYTHONIOENCODING"] == "utf-8"
            assert env["LANG"] == "C.UTF-8"
            assert env["LC_ALL"] == "C.UTF-8"
            assert env["NO_COLOR"] == "1"
            assert env["TERM"] == "dumb"

    def test_subprocess_argv_does_not_include_bare(self):
        """--bare loses keychain auth; design choice is to NEVER use it."""
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._fake_completed_process("ok")
            proc.returncode = 0
            mock_popen.return_value = proc

            ClaudeCodeExecutor().run_node(
                "trader",
                {"investment_plan": "..."},
                NodeSpec(agent_role="trader"),
            )

            argv = mock_popen.call_args.args[0]
            assert "--bare" not in argv

    def test_subprocess_argv_includes_print_and_stream_json(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._fake_completed_process("ok")
            proc.returncode = 0
            mock_popen.return_value = proc

            ClaudeCodeExecutor().run_node(
                "trader", {}, NodeSpec(agent_role="trader")
            )

            argv = mock_popen.call_args.args[0]
            assert "--print" in argv
            assert "--output-format" in argv
            # Either json or stream-json — both are JSON-parseable.
            idx = argv.index("--output-format")
            assert argv[idx + 1] in ("json", "stream-json")

    def test_subprocess_runs_in_clean_cwd(self):
        """Spawn from a temp dir so parent CLAUDE.md does not auto-load."""
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._fake_completed_process("ok")
            proc.returncode = 0
            mock_popen.return_value = proc

            ClaudeCodeExecutor().run_node(
                "trader", {}, NodeSpec(agent_role="trader")
            )

            cwd = mock_popen.call_args.kwargs.get("cwd")
            assert cwd is not None
            # The temp dir should not be the project root.
            assert "TradingAgents" not in str(cwd) or "tmp" in str(cwd).lower()


@pytest.mark.unit
class TestClaudeCodeExecutorResponseParsing:
    def test_parses_simple_result(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import NodeSpec

        events = [
            {"type": "system", "subtype": "init"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "Market trending up.",
                "session_id": "s1",
            },
        ]
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = ("\n".join(json.dumps(e) for e in events), "")
            proc.returncode = 0
            mock_popen.return_value = proc

            result = ClaudeCodeExecutor().run_node(
                "market_analyst",
                {"company_of_interest": "SPY"},
                NodeSpec(agent_role="market_analyst"),
            )

        assert "market_report" in result.state_delta or "messages" in result.state_delta
        # state_delta["messages"] is now a list[AIMessage] (dogfood-fixed: raw
        # strings auto-wrapped to HumanMessage by langgraph break downstream
        # tool_calls access). Check the free-text directly + via AIMessage.
        assert "Market trending up" in result.state_delta.get("market_report", "")
        msgs = result.state_delta.get("messages", [])
        if msgs:
            assert "Market trending up" in msgs[0].content

    def test_extracts_submit_portfolio_decision_tool_call(self):
        """When CLI invokes the decisions MCP submit_portfolio_decision tool,
        the executor MUST take the tool args as the structured state delta."""
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import NodeSpec

        events = [
            {"type": "system", "subtype": "init"},
            {
                "type": "item.completed",
                "item": {
                    "type": "tool_use",
                    "name": "submit_portfolio_decision",
                    "input": {
                        "rating": "Buy",
                        "executive_summary": "Take 5% position.",
                        "investment_thesis": "Strong Q3 earnings + index inclusion.",
                    },
                },
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "Done.",
                "session_id": "s1",
            },
        ]
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = ("\n".join(json.dumps(e) for e in events), "")
            proc.returncode = 0
            mock_popen.return_value = proc

            result = ClaudeCodeExecutor().run_node(
                "portfolio_manager",
                {},
                NodeSpec(agent_role="portfolio_manager"),
            )

        # Structured submission should surface in state_delta
        assert result.state_delta.get("portfolio_decision") is not None or "final_trade_decision" in result.state_delta
        assert result.executor_metadata.get("structured") is True


@pytest.mark.unit
class TestClaudeCodeExecutorFailureModes:
    def test_is_error_true_raises_executor_error(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import ExecutorError, NodeSpec

        events = [
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "Not logged in · Please run /login",
                "session_id": "s1",
            },
        ]
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = ("\n".join(json.dumps(e) for e in events), "")
            proc.returncode = 0
            mock_popen.return_value = proc

            with pytest.raises(ExecutorError) as excinfo:
                ClaudeCodeExecutor().run_node(
                    "trader", {}, NodeSpec(agent_role="trader")
                )
            assert "trader" == excinfo.value.node
            assert excinfo.value.reason in (
                "auth_failed", "is_error_true", "claude_code_error",
            )

    def test_rate_limit_text_detected_as_quota(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import ExecutorError, NodeSpec

        events = [
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "rate limit exceeded; try again in 3600 seconds",
                "session_id": "s1",
            },
        ]
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = ("\n".join(json.dumps(e) for e in events), "")
            proc.returncode = 0
            mock_popen.return_value = proc

            with pytest.raises(ExecutorError) as excinfo:
                ClaudeCodeExecutor().run_node(
                    "trader", {}, NodeSpec(agent_role="trader")
                )
            assert excinfo.value.reason == "quota_exhausted"

    def test_timeout_raises_executor_error(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import ExecutorError, NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.side_effect = subprocess.TimeoutExpired(
                cmd=["claude", "--print"], timeout=1
            )
            mock_popen.return_value = proc

            with pytest.raises(ExecutorError) as excinfo:
                ClaudeCodeExecutor(timeout_seconds=1).run_node(
                    "trader", {}, NodeSpec(agent_role="trader")
                )
            assert excinfo.value.reason == "timeout"
            # Ensure we attempted to kill the subprocess
            proc.kill.assert_called_once()


@pytest.mark.unit
class TestClaudeCodeExecutorIgnoresCallable:
    """Per design §D9: CLI executors MUST NOT call NodeSpec._callable."""

    def test_callable_not_invoked(self):
        from tradingagents.executors.claude_code import ClaudeCodeExecutor
        from tradingagents.executors.types import NodeSpec

        callable_was_invoked = []

        def should_not_be_called(state):
            callable_was_invoked.append(True)
            return {}

        events = [
            {"type": "result", "subtype": "success", "is_error": False, "result": "ok", "session_id": "s"},
        ]
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = ("\n".join(json.dumps(e) for e in events), "")
            proc.returncode = 0
            mock_popen.return_value = proc

            ClaudeCodeExecutor().run_node(
                "trader",
                {},
                NodeSpec(agent_role="trader", _callable=should_not_be_called),
            )

        assert callable_was_invoked == [], (
            "ClaudeCodeExecutor must ignore NodeSpec._callable; that field is "
            "the API mode shim only."
        )
