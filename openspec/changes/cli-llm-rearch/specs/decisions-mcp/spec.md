## ADDED Requirements

### Requirement: Decisions MCP server 啟動點

`tradingagents/decisions/mcp_server.py` SHALL 可獨立啟動為 MCP server,暴露 3 個 submit tools: `submit_research_plan`、`submit_trader_proposal`、`submit_portfolio_decision`。三個 tool 各自對應 `tradingagents/agents/schemas.py` 的 `ResearchPlan` / `TraderProposal` / `PortfolioDecision`。

#### Scenario: 獨立啟動 server
- **WHEN** 跑 `python -m tradingagents.decisions.mcp_server`
- **THEN** server 正常啟動,接受 `list_tools` 回 3 個 tool 描述

### Requirement: Submission API 不靠 MCP transport 也可呼叫

`tradingagents/decisions/` 模組 SHALL 暴露 3 個純 Python 函式 (`submit_research_plan`、`submit_trader_proposal`、`submit_portfolio_decision`),參數對應對應 schema 的真實欄位,內部用 Pydantic 驗證並回該 Pydantic 實例。SHALL 不依賴 MCP transport 也能被 import / 呼叫(MCP server 只是這些函式的 transport wrapper)。

#### Scenario: 直接呼叫 submit_portfolio_decision Python API
- **WHEN** 任何 Python code import 並呼 `submit_portfolio_decision(rating="Buy", executive_summary="...", investment_thesis="...")`
- **THEN** 回傳 `PortfolioDecision` Pydantic 實例,所有欄位填好

### Requirement: Tool 參數 schema 對齊既有 Pydantic schema

Decisions MCP server 每個 tool 的參數 schema SHALL 從 `tradingagents/agents/schemas.py` 既有 Pydantic schema 直接生成,SHALL NOT 重新定義 schema。

#### Scenario: submit_trader_proposal 參數對齊
- **WHEN** MCP client 跑 `list_tools` 取 `submit_trader_proposal` schema
- **THEN** schema 含欄位 `action` (enum: Buy/Hold/Sell)、`reasoning`、`entry_price` (optional)、`stop_loss` (optional)、`position_sizing` (optional),各欄位型別跟 `TraderProposal` Pydantic 定義一致

#### Scenario: submit_portfolio_decision 參數對齊
- **WHEN** MCP client 跑 `list_tools` 取 `submit_portfolio_decision` schema
- **THEN** schema 含欄位 `rating` (enum: Buy/Overweight/Hold/Underweight/Sell)、`executive_summary`、`investment_thesis`、`price_target` (optional)、`time_horizon` (optional)

#### Scenario: submit_research_plan 參數對齊
- **WHEN** MCP client 跑 `list_tools` 取 `submit_research_plan` schema
- **THEN** schema 含欄位 `recommendation` (enum: Buy/Overweight/Hold/Underweight/Sell)、`rationale`、`strategic_actions`

### Requirement: Schema 驗證失敗 strict reject

Decisions MCP server SHALL 在收到 schema-invalid 呼叫時拒絕並回明確錯誤(不接受、不部分填充、不靜默丟掉欄位)。

#### Scenario: submit_portfolio_decision 缺必填欄位
- **WHEN** CLI 呼叫 `submit_portfolio_decision(rating="Buy")`(缺 `executive_summary`、`investment_thesis`)
- **THEN** Pydantic ValidationError 攔到,SHALL NOT 接受該呼叫;CLI executor 端收到 error 後回 `ExecutorError(reason="schema_validation_failed", details=<error>)`

#### Scenario: submit_portfolio_decision rating 不合法
- **WHEN** CLI 呼叫 `submit_portfolio_decision(rating="MaybeBuy", ...)`(非 PortfolioRating enum)
- **THEN** Pydantic 拒絕並列出合法 enum 值 (Buy / Overweight / Hold / Underweight / Sell)

#### Scenario: submit_trader_proposal action 不合法
- **WHEN** CLI 呼叫 `submit_trader_proposal(action="StrongBuy", reasoning="...")`(非 TraderAction enum)
- **THEN** Pydantic 拒絕並列出合法 enum 值 (Buy / Hold / Sell)

### Requirement: API mode 不依賴 decisions MCP

`api` executor SHALL NOT 呼叫 decisions MCP server。API mode 透過 langchain `bind_structured` 直接拿 Pydantic 物件。Decisions MCP server 只服務 CLI executor。

#### Scenario: API mode 沒啟動 decisions MCP
- **WHEN** 跑 `tradingagents analyze --executor api SPY 2024-05-10` 且 decisions MCP server **沒**啟動
- **THEN** propagate 完整跑完無錯誤,Trader / PM node 透過 langchain 機制取得 Pydantic 物件
