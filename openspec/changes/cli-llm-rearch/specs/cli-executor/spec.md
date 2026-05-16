## ADDED Requirements

### Requirement: NodeExecutor protocol 抽象

`tradingagents/executors/base.py` SHALL 定義 `NodeExecutor` Protocol,介面為 `run_node(node_name: str, state: TradingState, spec: NodeSpec) -> NodeResult`。`NodeResult` SHALL 包含欄位 `state_delta: dict`、`raw_artifact_path: str | None`、`executor_metadata: dict`。

#### Scenario: 任一 executor 可被 graph 接受
- **WHEN** `tradingagents/graph/setup.py` 接受任一 NodeExecutor 實例作為參數
- **THEN** 不論該 executor 是 `api` / `claude-code` / `codex` / `gemini`,LangGraph node 都能呼叫 `executor.run_node(...)` 取得 `NodeResult`

### Requirement: Claude Code CLI executor

`tradingagents/executors/claude_code.py` SHALL 透過 subprocess 呼叫 `claude --print --output-format json --mcp-config <config>` 執行 agent 工作,parse JSON 輸出取得 tool call(decisions MCP submit_decision)。

#### Scenario: Claude Code executor 跑 PM node
- **WHEN** graph 跑到 PortfolioManager node,executor=claude-code
- **THEN** spawn `claude --print --output-format json ...`,Claude Code session 呼叫 `submit_portfolio_decision(rating=..., allocation=..., rationale=...)` MCP tool,parent process 從 tool call payload 取得 `PortfolioDecision` Pydantic 物件作為 `NodeResult.state_delta`

#### Scenario: Claude Code session timeout
- **WHEN** claude subprocess 跑超過 60 秒未回(default per-node timeout)
- **THEN** 父 process kill subprocess,回 `ExecutorError(reason="timeout", node=<node_name>)`,LangGraph checkpoint 存當前 state

### Requirement: Codex CLI executor

`tradingagents/executors/codex.py` SHALL 透過 subprocess 呼叫 `codex exec --json -s read-only --mcp-config <config> ...` 執行 agent 工作。SHALL parse `turn.completed` 跟 `item.completed` 事件取得 final agent_message。

#### Scenario: Codex executor 跑 analyst node
- **WHEN** graph 跑到 MarketAnalyst node,executor=codex,可用 tools 包含 dataflows MCP
- **THEN** spawn `codex exec --json ...`,Codex 自行呼叫 `get_stock_data` / `get_indicators` 等 MCP tool,最後產出 market_report 寫入 state_delta

### Requirement: Gemini CLI executor

`tradingagents/executors/gemini.py` SHALL 透過 subprocess 呼叫 Gemini CLI 執行 agent 工作。若 Gemini CLI 原生支援 MCP client,SHALL 走 decisions MCP `submit_decision` 拿 schema-valid 輸出;若不支援,SHALL fallback 為 prompt + JSON parse + 最多 2 次 retry。

#### Scenario: Gemini executor MCP path
- **WHEN** Gemini CLI 確認支援 MCP 且跑到 Trader node
- **THEN** Trader 工作完成時 Gemini 呼叫 `submit_trader_proposal(...)` MCP tool,parent 拿到 Pydantic `TraderProposal`

#### Scenario: Gemini executor JSON fallback path
- **WHEN** Gemini CLI 不支援 MCP,跑到 Trader node
- **THEN** prompt 明示「output ONLY this JSON schema」,parent 用 `json.loads` 解 stdout,若 schema validation 失敗則 prompt 帶上次錯誤後最多 retry 2 次,3 次都失敗回 `ExecutorError(reason="schema_parse_failed")`

### Requirement: CLI executor Windows utf-8 環境

所有 CLI executor SHALL 在 spawn subprocess 時設定完整 utf-8 環境變數覆寫: `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`LANG=C.UTF-8`、`LC_ALL=C.UTF-8`、`NO_COLOR=1`、`TERM=dumb`。stdout/stderr 讀取 SHALL 用 `bytes` 模式並以 `errors="replace"` decode 為 utf-8。

#### Scenario: 繁中 locale Windows 機器跑 CLI mode
- **WHEN** 在 cp950 預設 Windows 機器跑 `tradingagents analyze --executor claude-code SPY 2024-05-10`
- **THEN** propagate 完整跑完不撞 `UnicodeDecodeError` 或 `UnicodeEncodeError`,即使中途有中文 / U+26A0 等 non-ASCII 字元穿過 subprocess pipe

### Requirement: CLI executor quota / rate limit 偵測

CLI executor SHALL 在 subprocess 輸出中偵測 quota / rate-limit 訊號(各 CLI 文字格式可能不同),統一回 `ExecutorError(reason="quota_exhausted", node=<name>, raw_error=<original>)`。

#### Scenario: Claude Code 配額耗盡
- **WHEN** Claude Code CLI 回覆 rate-limit 或 quota-exhausted 錯誤
- **THEN** executor 回 `ExecutorError(reason="quota_exhausted")`,LangGraph checkpoint 存當前 state,使用者看到明確訊息「<node> failed: claude-code quota exhausted at <timestamp>」

### Requirement: CLI executor fail-closed at node boundary

CLI executor 失敗時 SHALL NOT 自動 fallback 到其他 executor。propagate SHALL 停在失敗 node,checkpoint 保存,等使用者明示用 `--resume --executor <name>` 接續。

#### Scenario: CLI executor 失敗不自動切 API
- **WHEN** CLI executor 在 node 6 quota_exhausted
- **THEN** 系統 SHALL NOT 自動用 API executor 重試 node 6;SHALL exit 非零並顯示 resume 指令建議

### Requirement: CLI executor 不從 stdout 取結構化輸出

CLI executor SHALL NOT 將人類可讀 stdout 解析為權威 trading decision 來源。需要 schema-valid 輸出(TraderProposal / PortfolioDecision / Rating)時,SHALL 透過 decisions MCP tool call payload 取得。stdout 僅可作為 transcript 留檔。

#### Scenario: 不從 markdown 抓 rating
- **WHEN** PortfolioManager 透過 Claude Code executor 產生輸出,且該 CLI 有透過 MCP submit_portfolio_decision
- **THEN** 系統取 MCP tool call 的 `rating` 參數作為權威值,SHALL NOT 用 regex `\*\*Rating\*\*: (\w+)` 解析 stdout markdown
