## ADDED Requirements

### Requirement: Decisions MCP server 啟動點

`tradingagents/decisions/mcp_server.py` SHALL 可獨立啟動為 MCP server,暴露 3 個 submit tools: `submit_trader_proposal`、`submit_portfolio_decision`、`submit_rating`。

#### Scenario: 獨立啟動 server
- **WHEN** 跑 `python -m tradingagents.decisions.mcp_server`
- **THEN** server 正常啟動,接受 `list_tools` 回 3 個 tool 描述

### Requirement: Tool 參數 schema 對齊既有 Pydantic schema

Decisions MCP server 每個 tool 的參數 schema SHALL 從 `tradingagents/agents/utils/schemas.py`(或對應位置)既有 Pydantic schema 直接生成,SHALL NOT 重新定義 schema。三個 tool 對應的 schema 為 `TraderProposal`、`PortfolioDecision`、`Rating`(各自欄位於 brainstorm design §3.4 已定)。

#### Scenario: submit_trader_proposal 參數對齊
- **WHEN** MCP client 跑 `list_tools` 取 `submit_trader_proposal` schema
- **THEN** schema 含欄位 `qty`、`entry`、`exit`、`stop_loss`、`rationale`,各欄位型別跟 `TraderProposal` Pydantic 定義一致

### Requirement: Schema 驗證失敗 strict reject

Decisions MCP server SHALL 在收到 schema-invalid 呼叫時拒絕並回明確錯誤(不接受、不部分填充、不靜默丟掉欄位)。

#### Scenario: submit_portfolio_decision 缺欄位
- **WHEN** CLI 呼叫 `submit_portfolio_decision(rating="Buy")`(缺 `allocation`、`rationale`)
- **THEN** MCP server 回錯誤訊息明確指出缺失欄位,SHALL NOT 接受該呼叫,CLI executor 收到 error 後回 `ExecutorError(reason="schema_validation_failed", details=<error>)`

#### Scenario: submit_rating 不合法值
- **WHEN** CLI 呼叫 `submit_rating(scale="invalid-scale", value="x")`
- **THEN** MCP server 拒絕,回錯誤訊息列出合法 scale 值跟 value 型別要求

### Requirement: API mode 不依賴 decisions MCP

`api` executor SHALL NOT 呼叫 decisions MCP server。API mode 透過 langchain `bind_structured` 直接拿 Pydantic 物件。Decisions MCP server 只服務 CLI executor。

#### Scenario: API mode 沒啟動 decisions MCP
- **WHEN** 跑 `tradingagents analyze --executor api SPY 2024-05-10` 且 decisions MCP server **沒**啟動
- **THEN** propagate 完整跑完無錯誤,Trader / PM node 透過 langchain 機制取得 Pydantic 物件
