---
description: Run a TradingAgents analysis from inside Claude Code, defaulting to the claude-code subscription executor
---

# /trade

Thin wrapper around `tradingagents analyze --executor claude-code`. Lets you
trigger a full multi-agent trading run from inside a Claude Code session
without leaving the chat.

**Default behaviour**: invokes the Python entry point with the `claude-code`
executor — every LangGraph node spawns a child `claude --print` subprocess
that uses your Claude Code subscription. Zero token cost per call (just
your subscription).

## How to use it

```
/trade <TICKER> <YYYY-MM-DD>
/trade SPY 2024-05-10
/trade SPY 2024-05-10 --executor api          # fall back to langchain API mode
/trade NVDA 2024-05-10 --executor codex       # delegate to Codex CLI
/trade TSLA 2024-05-10 --executor gemini      # delegate to Gemini CLI
```

## What this slash command does (when invoked)

Run `tradingagents analyze` with the arguments parsed from the user message:

1. Parse the ticker symbol (first positional arg) and date (second positional
   arg, format `YYYY-MM-DD`).
2. Parse any `--executor` flag override; default to `--executor claude-code`.
3. Parse `--checkpoint` / `--clear-checkpoints` flags if present.
4. Execute `tradingagents analyze --executor <mode> [...other flags...]`
   from the project root. The CLI itself runs the interactive selectors
   for analysts and research depth.

If `--executor claude-code` is the active mode and you are running this
from within a Claude Code session, the executor will spawn nested
`claude --print` child subprocesses. Per
`tradingagents/executors/CLAUDE_CODE_NESTING_NOTES.md`: nesting works,
keychain auth carries over, expect ~2-3s of overhead per agent invocation.

## Why this command exists

The TradingAgents Python entry point (`tradingagents analyze`) is the
canonical orchestration — `/trade` is a thin alias so users do NOT have to
switch terminals. There is no separate orchestration in this slash command;
the LangGraph node order, debate rounds, and decision schemas are owned by
`tradingagents/graph/` and would drift if duplicated here.

Spec: `openspec/changes/cli-llm-rearch/specs/trade-slash-command/spec.md`.
