# Nested Claude Code session — smoke test findings

**Date**: 2026-05-16
**Question** (design.md §11 Q1): Running `/trade` inside a Claude Code session
spawns a child `claude --print ...` subprocess. Is nesting allowed? Does auth
carry through? What's the cost shape?

## Findings

### Nesting is allowed

A Claude Code session can spawn `claude --print` as a child process. No
sandbox aborts. The child runs to completion and returns JSON output on stdout.

### Auth carries through via keychain — when --bare is NOT used

Tested two modes:

| Mode | Auth result | Cost shape |
|---|---|---|
| `claude --print --bare ...` | "Not logged in · Please run /login" (is_error=true) | $0 (no API call made) |
| `claude --print ...` (no --bare) | Works; uses keychain OAuth | ~$0.16-0.29 per call equiv. API cost (subscription-billed, user does not pay this per-call) |

`--bare` strictly requires `ANTHROPIC_API_KEY` env var (per its help text:
"Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings
(OAuth and keychain are never read)"). For subscription users this defeats the
"no token cost" goal, so **the claude-code executor MUST NOT use --bare** by
default.

### Working-directory choice affects context size

Spawn from a directory with `CLAUDE.md`: ~46,755 cache-creation tokens.
Spawn from a directory without `CLAUDE.md`: ~24,170 cache-creation +
~22,357 cache-read tokens.

The 22k cache-read piece comes from a previous spawn warming the cache. After
the first node in a propagate, subsequent nodes amortize down significantly.

The remaining ~24k tokens is the Claude Code base system prompt + tool
descriptions — there is no flag to skip this. It's the cost of using Claude
Code's full capability surface.

For the executor: spawn from a temp working dir to keep the CLAUDE.md load
out, then rely on cache reuse across nodes within one propagate.

### Output format

`--output-format json` returns a single JSON object with these key fields:

- `result`: the model's final text response
- `is_error`: bool — important; success status (`subtype: "success"` is misleading; check `is_error`)
- `total_cost_usd`: API-equivalent cost (0 if cache-only or auth-failed)
- `model_usage`: per-model cost breakdown (haiku/opus inputs, output, cache)
- `session_id`: trace identifier
- `usage`: cache_creation / cache_read / input / output token counts
- `permission_denials`: array (empty when no tool/file access was denied)

`--output-format stream-json` emits a sequence of JSON events including
`item.completed` for each tool call / reasoning step / agent message — better
for parsing tool calls in real time (e.g., decisions MCP submit_decision).

### Exit code is misleading

Both successful and `is_error: true` outcomes returned `exit code 0`. **The
executor MUST check `is_error` in the parsed JSON, not the subprocess exit
code, to detect failure.**

## Implementation choices for `claude_code.py`

1. Spawn from `tempfile.TemporaryDirectory()` to avoid parent `CLAUDE.md`
   auto-load.
2. Do NOT pass `--bare` (keep keychain auth so the user's subscription is used).
3. Use `--output-format stream-json` for per-step parsing; final `result` from
   the terminal event is the state delta when no MCP tool call surfaces.
4. Parse for `submit_research_plan` / `submit_trader_proposal` /
   `submit_portfolio_decision` MCP tool calls; their parameters are the
   schema-valid state delta.
5. Treat any of these as `ExecutorError(reason=...)`:
   - `is_error: true` in result event
   - `result` containing "rate limit" / "quota" / "Not logged in"
   - subprocess wall-clock time > 60s (configurable per node)
6. Set the full utf-8 env block per design §7.1.

## Cost expectations (real-talk)

- ~2-3 seconds per spawn just to load context (not counting reasoning time)
- 30-50 agent calls per propagate × 2-3s = 1.5-2.5 minutes of pure overhead
- Plus actual reasoning time per node (10-60s depending on complexity)
- Total CLI mode propagate: estimate **5-10x slower than API mode**
  (matches design §6.1 risk accepted)
- For subscription users: no $ cost per call. For ANTHROPIC_API_KEY users
  forced through `--bare`: same cost as API mode plus subprocess overhead —
  net loss; don't do this.
