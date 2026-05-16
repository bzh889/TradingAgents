"""Phase 5 / task 5.2 + 5.4 — Codex / Gemini executor unit tests.

Mirrors test_claude_code_executor.py: mocked subprocess, asserts on argv,
env, parsing, and failure modes. Real CLI invocations are operational
verification (defer to user-driven runs that consume subscription quota).
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# CodexExecutor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCodexExecutorBasics:
    def test_can_import(self):
        from tradingagents.executors.codex import CodexExecutor  # noqa: F401

    def test_has_name_codex(self):
        from tradingagents.executors.codex import CodexExecutor

        assert CodexExecutor().name == "codex"

    def test_implements_node_executor_protocol(self):
        from tradingagents.executors.base import NodeExecutor
        from tradingagents.executors.codex import CodexExecutor

        ex = CodexExecutor()
        assert hasattr(ex, "run_node")
        assert callable(ex.run_node)
        assert isinstance(ex, NodeExecutor)

    def test_supports_structured(self):
        from tradingagents.executors.codex import CodexExecutor

        assert CodexExecutor().supports_structured() is True


@pytest.mark.unit
class TestCodexExecutorArgvAndEnv:
    def _stream(self, *events):
        return ("\n".join(json.dumps(e) for e in events), "")

    def test_argv_has_exec_json_read_only(self):
        from tradingagents.executors.codex import CodexExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "turn.completed", "usage": {}},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            CodexExecutor().run_node("trader", {}, NodeSpec(agent_role="trader"))

            argv = mock_popen.call_args.args[0]
            assert argv[0] == "codex"
            assert "exec" in argv
            assert "--json" in argv
            i = argv.index("-s")
            assert argv[i + 1] == "read-only"

    def test_utf8_env_block_in_subprocess(self):
        from tradingagents.executors.codex import CodexExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}},
                {"type": "turn.completed", "usage": {}},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            CodexExecutor().run_node("trader", {}, NodeSpec(agent_role="trader"))

            env = mock_popen.call_args.kwargs["env"]
            assert env["PYTHONUTF8"] == "1"
            assert env["LC_ALL"] == "C.UTF-8"


@pytest.mark.unit
class TestCodexExecutorParsing:
    def _stream(self, *events):
        return ("\n".join(json.dumps(e) for e in events), "")

    def test_extracts_submit_trader_proposal(self):
        from tradingagents.executors.codex import CodexExecutor
        from tradingagents.executors.types import NodeSpec

        events = [
            {"type": "thread.started", "thread_id": "abc"},
            {
                "type": "item.completed",
                "item": {
                    "type": "tool_use",
                    "name": "submit_trader_proposal",
                    "input": {
                        "action": "Buy",
                        "reasoning": "Strong momentum.",
                    },
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}},
        ]
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(*events)
            proc.returncode = 0
            mock_popen.return_value = proc

            result = CodexExecutor().run_node(
                "trader", {}, NodeSpec(agent_role="trader")
            )
        assert result.state_delta.get("trader_investment_plan") is not None
        assert result.executor_metadata.get("structured") is True

    def test_rate_limit_signals_quota_exhausted(self):
        from tradingagents.executors.codex import CodexExecutor
        from tradingagents.executors.types import ExecutorError, NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "error", "message": "rate limit hit; try again in 600 seconds"},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            with pytest.raises(ExecutorError) as excinfo:
                CodexExecutor().run_node(
                    "trader", {}, NodeSpec(agent_role="trader")
                )
            assert excinfo.value.reason == "quota_exhausted"

    def test_timeout_kills_subprocess(self):
        from tradingagents.executors.codex import CodexExecutor
        from tradingagents.executors.types import ExecutorError, NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.side_effect = subprocess.TimeoutExpired(
                cmd=["codex", "exec"], timeout=1
            )
            mock_popen.return_value = proc

            with pytest.raises(ExecutorError) as excinfo:
                CodexExecutor(timeout_seconds=1).run_node(
                    "trader", {}, NodeSpec(agent_role="trader")
                )
            assert excinfo.value.reason == "timeout"
            proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# GeminiExecutor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeminiExecutorBasics:
    def test_can_import(self):
        from tradingagents.executors.gemini import GeminiExecutor  # noqa: F401

    def test_has_name_gemini(self):
        from tradingagents.executors.gemini import GeminiExecutor

        assert GeminiExecutor().name == "gemini"

    def test_implements_node_executor_protocol(self):
        from tradingagents.executors.base import NodeExecutor
        from tradingagents.executors.gemini import GeminiExecutor

        assert isinstance(GeminiExecutor(), NodeExecutor)


@pytest.mark.unit
class TestGeminiExecutorArgvAndEnv:
    def _stream(self, *events):
        return ("\n".join(json.dumps(e) for e in events), "")

    def test_argv_has_prompt_and_stream_json(self):
        from tradingagents.executors.gemini import GeminiExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "message", "content": "ok"},
                {"type": "done", "usage": {}},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            GeminiExecutor().run_node(
                "market_analyst", {}, NodeSpec(agent_role="market_analyst")
            )
            argv = mock_popen.call_args.args[0]
            assert argv[0] == "gemini"
            assert "-p" in argv
            assert "-o" in argv
            i = argv.index("-o")
            assert argv[i + 1] == "stream-json"
            assert "-y" in argv
            assert "--skip-trust" in argv

    def test_argv_with_allowed_mcp_servers(self):
        from tradingagents.executors.gemini import GeminiExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "message", "content": "ok"},
                {"type": "done", "usage": {}},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            GeminiExecutor(
                allowed_mcp_servers=["tradingagents-decisions", "tradingagents-dataflows"]
            ).run_node("trader", {}, NodeSpec(agent_role="trader"))

            argv = mock_popen.call_args.args[0]
            assert "--allowed-mcp-server-names" in argv
            idx = argv.index("--allowed-mcp-server-names")
            assert argv[idx + 1] == "tradingagents-decisions"
            assert argv[idx + 2] == "tradingagents-dataflows"

    def test_utf8_env_block(self):
        from tradingagents.executors.gemini import GeminiExecutor
        from tradingagents.executors.types import NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "message", "content": "ok"},
                {"type": "done", "usage": {}},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            GeminiExecutor().run_node(
                "trader", {}, NodeSpec(agent_role="trader")
            )
            env = mock_popen.call_args.kwargs["env"]
            assert env["NO_COLOR"] == "1"
            assert env["TERM"] == "dumb"


@pytest.mark.unit
class TestGeminiExecutorParsing:
    def _stream(self, *events):
        return ("\n".join(json.dumps(e) for e in events), "")

    def test_single_json_output_with_tool_call(self):
        """Output_format=json returns one JSON object; tool_calls in that object."""
        from tradingagents.executors.gemini import GeminiExecutor
        from tradingagents.executors.types import NodeSpec

        single_obj = {
            "response": "Submitted portfolio decision.",
            "tool_calls": [
                {
                    "name": "submit_portfolio_decision",
                    "arguments": {
                        "rating": "Buy",
                        "executive_summary": "Take 5% position.",
                        "investment_thesis": "Strong fundamentals.",
                    },
                }
            ],
            "usage": {"input_tokens": 200, "output_tokens": 80},
        }
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = (json.dumps(single_obj), "")
            proc.returncode = 0
            mock_popen.return_value = proc

            result = GeminiExecutor().run_node(
                "portfolio_manager",
                {},
                NodeSpec(agent_role="portfolio_manager"),
            )
        assert result.state_delta.get("final_trade_decision") is not None
        assert result.state_delta.get("portfolio_decision") is not None
        assert result.executor_metadata.get("structured") is True

    def test_quota_exhausted_via_error_event(self):
        from tradingagents.executors.gemini import GeminiExecutor
        from tradingagents.executors.types import ExecutorError, NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "error", "message": "Quota exceeded for your account"},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            with pytest.raises(ExecutorError) as excinfo:
                GeminiExecutor().run_node(
                    "trader", {}, NodeSpec(agent_role="trader")
                )
            assert excinfo.value.reason == "quota_exhausted"

    def test_timeout(self):
        from tradingagents.executors.gemini import GeminiExecutor
        from tradingagents.executors.types import ExecutorError, NodeSpec

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.side_effect = subprocess.TimeoutExpired(
                cmd=["gemini", "-p"], timeout=1
            )
            mock_popen.return_value = proc

            with pytest.raises(ExecutorError) as excinfo:
                GeminiExecutor(timeout_seconds=1).run_node(
                    "trader", {}, NodeSpec(agent_role="trader")
                )
            assert excinfo.value.reason == "timeout"
            proc.kill.assert_called_once()


@pytest.mark.unit
class TestBothExecutorsIgnoreCallable:
    """CLI executors MUST NOT call NodeSpec._callable per §D9."""

    def _stream(self, *events):
        return ("\n".join(json.dumps(e) for e in events), "")

    def test_codex_ignores_callable(self):
        from tradingagents.executors.codex import CodexExecutor
        from tradingagents.executors.types import NodeSpec

        invoked = []
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}},
            {"type": "turn.completed", "usage": {}},
        ]
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(*events)
            proc.returncode = 0
            mock_popen.return_value = proc

            CodexExecutor().run_node(
                "trader",
                {},
                NodeSpec(agent_role="trader", _callable=lambda s: invoked.append(1) or {}),
            )
        assert invoked == []

    def test_gemini_ignores_callable(self):
        from tradingagents.executors.gemini import GeminiExecutor
        from tradingagents.executors.types import NodeSpec

        invoked = []
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = self._stream(
                {"type": "message", "content": "ok"},
                {"type": "done", "usage": {}},
            )
            proc.returncode = 0
            mock_popen.return_value = proc

            GeminiExecutor().run_node(
                "trader",
                {},
                NodeSpec(agent_role="trader", _callable=lambda s: invoked.append(1) or {}),
            )
        assert invoked == []
