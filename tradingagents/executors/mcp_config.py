"""Build the per-run MCP config that CLI executors pass to their subprocess.

Claude Code, Codex, and Gemini all accept an `--mcp-config <file>` flag that
points to a JSON file declaring which MCP servers the agent may talk to.
We auto-generate that file for the user so they do not have to maintain it
by hand — the claude-code subprocess (or codex/gemini) spawns the
dataflows + decisions MCP servers itself when it needs a tool.

The config uses stdio transport (each MCP server is launched as a child of
the LLM CLI; communication is a pair of pipes). The command we register is
the same Python interpreter running tradingagents — that way the server has
the project's modules on its sys.path without an editable install dance.

Layout:

    {
      "mcpServers": {
        "tradingagents-dataflows": {
          "command": "<python>",
          "args": ["-m", "tradingagents.dataflows.mcp_server"],
          "env": {...optional...}
        },
        "tradingagents-decisions": {
          "command": "<python>",
          "args": ["-m", "tradingagents.decisions.mcp_server"]
        }
      }
    }

Phase 4b operational item. See openspec/changes/cli-llm-rearch/tasks.md §4.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional


def build_mcp_config_dict(
    extra_env: Optional[dict[str, str]] = None,
) -> dict:
    """Return the JSON-shaped dict for an `--mcp-config` file."""
    python_exe = sys.executable
    base_env = {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    if extra_env:
        base_env.update(extra_env)
    return {
        "mcpServers": {
            "tradingagents-dataflows": {
                "command": python_exe,
                "args": ["-m", "tradingagents.dataflows.mcp_server"],
                "env": dict(base_env),
            },
            "tradingagents-decisions": {
                "command": python_exe,
                "args": ["-m", "tradingagents.decisions.mcp_server"],
                "env": dict(base_env),
            },
        }
    }


def write_mcp_config(
    target_dir: Optional[Path] = None,
    extra_env: Optional[dict[str, str]] = None,
) -> Path:
    """Write the MCP config JSON to disk and return the absolute path.

    `target_dir` keeps the config alongside the run's reports so the user can
    inspect it; if None we use a tempfile (auto-cleaned by the OS).

    The config has to live on disk because `claude --mcp-config <path>` and
    `codex exec --config mcp_config=<path>` both read from a file (not stdin).
    """
    payload = build_mcp_config_dict(extra_env=extra_env)
    if target_dir is not None:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "mcp-config.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    fd, path = tempfile.mkstemp(
        prefix="tradingagents-mcp-",
        suffix=".json",
        text=True,
    )
    os.close(fd)
    path_obj = Path(path)
    path_obj.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path_obj
