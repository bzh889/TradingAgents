## Why

TradingAgents 目前每次跑 propagate 要打 10-30 次 LLM API,token 成本累積很快;但使用者已經付 Claude Code / Codex / Gemini CLI 訂閱費,可以零邊際成本地用同等級或更強的模型,還可以善用 CLI 內建的 subagent / Bash / Read / WebFetch 工具自主性。本改造新增訂閱制 CLI 執行模式,API 模式完全保留,使用者執行時互動選擇用哪種。

## What Changes

- **新增** per-node executor 抽象 `tradingagents/executors/`(`base.py`、`api.py`、`claude_code.py`、`codex.py`、`gemini.py`),每個 LangGraph node 在執行時委派給選定的 executor
- **新增** `tradingagents.decisions.mcp_server`,暴露 schema-validated 工具(`submit_trader_proposal`、`submit_portfolio_decision`、`submit_rating`),CLI executor 用這個拿結構化輸出
- **新增** `tradingagents.dataflows.mcp_server`,把現有 yfinance / alpha_vantage routing 包成 MCP server。API mode 跟 CLI mode 共用
- **修改** `cli/utils.py` 互動選單,加兩段式選擇:Step 1 execution mode(api / claude-code / codex / gemini)、Step 2 conditional provider/executor config
- **修改** `tradingagents/graph/setup.py`,每個 node factory 接受 executor 參數
- **新增** `.claude/commands/trade.md` slash command,thin wrapper 呼叫 `tradingagents analyze --executor claude-code`
- LangGraph orchestration、`tradingagents/agents/`、`tradingagents/llm_clients/`、persistence 路徑跟格式**全部不動**(API mode 零破壞、兩模式同檔同格式跨模式 reflection 可互通)
- CLI mode 失敗(quota / timeout / parse / tool)**fail-closed at node boundary**,使用者用 `--resume --executor api` 切換補完;**沒有**自動 mid-flight fallback

## Capabilities

### New Capabilities

- `executor-mode-selection`: 互動式選單從單一階段(provider 選擇)變兩段(execution mode 選擇 → conditional config),`cli/utils.py` 修改
- `cli-executor`: NodeExecutor protocol + 三個 CLI 實作(claude-code / codex / gemini),per-node subprocess 模型,Windows utf-8 環境變數處理,fail-closed 失敗語意
- `api-executor`: 把現有 langchain 路徑包成 `executors/api.py`(NodeExecutor 介面),完全相容現行行為作為 baseline
- `dataflows-mcp`: 現有 dataflows routing 包成 MCP server,API mode 跟 CLI mode 共用
- `decisions-mcp`: schema-validated MCP tools(TraderProposal / PortfolioDecision / Rating)取代 markdown heuristic parsing,只給 CLI executor 用
- `trade-slash-command`: `.claude/commands/trade.md` thin wrapper,讓 Claude Code session 內可直接呼叫 trading 流程

### Modified Capabilities

無 — `openspec/specs/` 目前是空的(本 project 首次走 OpenSpec spec-driven 流程),所有新增的 spec 都是 New Capabilities。

## Impact

- **新增程式碼**: `tradingagents/executors/` 全新模組;`tradingagents/dataflows/mcp_server.py`;`tradingagents/decisions/mcp_server.py`;`.claude/commands/trade.md`;`openspec/specs/` 6 個新 capability spec
- **修改程式碼**: `cli/utils.py`(選單兩段化)、`tradingagents/graph/setup.py`(每個 node factory 多吃 executor 參數)、`main.py`(可選的範例更新)
- **零修改**: `tradingagents/agents/**`、`tradingagents/llm_clients/**`、`tradingagents/dataflows/interface.py`(MCP server 只是包一層,不動 routing 邏輯)、persistence(`~/.tradingagents/memory/`、SQLite checkpoint、`./reports/`)
- **依賴**: 可能新增 `mcp` Python SDK(`fastmcp` 或官方 mcp-server SDK)。LangGraph、langchain 系列、yfinance、redis 等既有依賴**不升級**
- **效能**: CLI mode 預估比 API mode 慢 5-10x(per-agent subprocess × 1-2s 啟動 × 30-50 node)— 詳見 design §6.1 risk accepted
- **可重現性 / audit**: persistence 主檔不加 provenance fields(維持兩模式同格式),per-run 補 `./reports/{TICKER}_{TIMESTAMP}/_meta.json` 記 executor / cli_command / tool_versions / token usage,獨立檔不影響 canonical memory_log
- **Windows 編碼**: CLI subprocess 必須顯式設 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` + `LANG=C.UTF-8` + `LC_ALL=C.UTF-8` + `NO_COLOR=1` + `TERM=dumb`,stdout decode 用 `errors="replace"`,結構化輸出走 MCP tool payload 不走 stdout parsing
- **不影響**: 既有 108 tests + 42 subtests 跑 API mode 必須完全綠(regression baseline)
- **平台支援**: CLI mode 預設假設 Claude Code / Codex / Gemini CLI 已在 PATH;executor 啟動時驗證,缺則明確錯誤
- **訂閱配額風險**: CLI run 撞到 quota 不自動降級到 API mode,fail-closed 顯示明確錯誤 + checkpoint 保存,使用者明示 resume(設計選擇,詳 design §6 / §3.8)
