## ADDED Requirements

### Requirement: Dataflows MCP server 啟動點

`tradingagents/dataflows/mcp_server.py` SHALL 可獨立啟動為 MCP server,並暴露 dataflows 9 個 tool(`get_stock_data`、`get_indicators`、`get_fundamentals`、`get_news`、`get_global_news`、`get_insider_transactions`、`get_balance_sheet`、`get_cashflow`、`get_income_statement`)。

#### Scenario: 獨立啟動 server
- **WHEN** 跑 `python -m tradingagents.dataflows.mcp_server`
- **THEN** server 正常啟動,監聽 MCP stdio 或設定的 transport,接受 `list_tools` 請求並回 9 個 tool 描述

### Requirement: Dataflows MCP 內部沿用既有 routing

Dataflows MCP server SHALL 內部呼叫 `tradingagents/dataflows/interface.py` 既有 routing(yfinance / alpha_vantage + fallback 鏈),SHALL NOT 重寫 routing 邏輯。當 yfinance 撞到 `AlphaVantageRateLimitError` 時 SHALL 仍照既有 fallback 路徑切換到 alpha_vantage。

#### Scenario: yfinance routing 維持
- **WHEN** 透過 MCP 呼叫 `get_stock_data(ticker="SPY", date="2024-05-10")`,預設 vendor=yfinance
- **THEN** 內部呼叫 `dataflows/interface.get_stock_data(...)`,結果跟直接呼 Python function 一致

#### Scenario: Alpha Vantage fallback
- **WHEN** 透過 MCP 呼叫 `get_indicators` 但 yfinance hit rate-limit
- **THEN** 既有 fallback 啟動切到 alpha_vantage,MCP 回應仍是有效資料(透明 fallback)

### Requirement: Tool 參數 schema 對齊既有 Python signature

Dataflows MCP server 每個 tool 的參數 schema(由 MCP 暴露)SHALL 跟 `dataflows/interface.py` 對應 Python function 的 signature 對齊(param names + types + required vs optional)。

#### Scenario: get_stock_data 參數 schema
- **WHEN** MCP client 跑 `list_tools` 並取得 `get_stock_data` schema
- **THEN** schema 含 `ticker: str` (required)、`date: str` (required)、`vendor: str = "yfinance"` (optional with default)

### Requirement: Dataflows MCP 不暴露任何寫盤操作

Dataflows MCP server SHALL 只暴露 read-only tools(資料讀取)。SHALL NOT 暴露 cache 寫入、報告寫入、memory log 寫入或任何修改 filesystem 狀態的 tool。

#### Scenario: 嘗試列出 write tool
- **WHEN** MCP client 跑 `list_tools`
- **THEN** 9 個 tool 全部是 read-only;沒有任何工具名稱含 `set_` / `write_` / `delete_` / `update_` 等前綴
