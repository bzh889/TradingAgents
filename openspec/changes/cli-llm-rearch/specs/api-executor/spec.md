## ADDED Requirements

### Requirement: API executor 包現有 langchain 行為

`tradingagents/executors/api.py` SHALL 實作 `NodeExecutor` 介面,內部呼叫現有 `tradingagents/llm_clients/` 既有的 langchain ChatModel 邏輯。其行為 SHALL 跟 master 分支沒重構前的行為完全相同(rating、structured output、tool call、reflection、checkpoint 互動全部一致)。

#### Scenario: API mode regression baseline
- **WHEN** 跑 `pytest -q` 在 phase 1 commit 之後
- **THEN** 既有 108 tests + 42 subtests 全綠,no new warnings(除既有 langgraph 第三方 PendingDeprecationWarning)

#### Scenario: API mode 跑 SPY 2024-05-10 行為不變
- **WHEN** 在 phase 1 commit 跑 `tradingagents analyze SPY 2024-05-10 --executor api`(以 mock provider 確保 deterministic)
- **THEN** 產出的 final_state dict、memory_log entry、checkpoint DB 跟 master 跑同 input 產出 byte-equivalent 結果(以對應 schema 比較,非 raw byte)

### Requirement: API executor 透過 `NodeSpec._callable` shim 呼叫既有 agent 函式

API executor 的 `run_node(node_name, state, spec)` SHALL 在 `spec._callable` 不為 None 時直接呼叫該 callable 取得 state delta,SHALL NOT 重新實作 agent 邏輯。`spec._callable` 為 `Callable[[dict], dict]`,即 LangGraph 既有 node 簽名。若 `spec._callable` 為 None,SHALL 回 `ExecutorError(reason="no_callable")`。

#### Scenario: API executor 直接 delegate 給 agent 函式
- **WHEN** `setup.py` 包 `create_market_analyst(llm)` 為 `NodeSpec(_callable=fn)` 並呼 `api_executor.run_node("market_analyst", state, spec)`
- **THEN** APIExecutor 內部直接呼 `fn(state)` 取得 dict,把該 dict 包成 `NodeResult.state_delta`,executor_metadata 含 `{"executor": "api", "agent_role": "market_analyst"}`

#### Scenario: API executor 缺 _callable 報明確錯誤
- **WHEN** 呼 `api_executor.run_node(..., NodeSpec(agent_role="x"))` 沒設 `_callable`
- **THEN** 拋 `ExecutorError(reason="no_callable", node="x")`

### Requirement: API executor 用 langchain bind_structured 拿 schema 輸出

API executor 跑到 Trader / PortfolioManager 等需要 schema 的 node 時 SHALL 用 `bind_structured(llm, schema)` 取得 Pydantic 物件。SHALL NOT 走 decisions MCP(那是 CLI executor 專用)。

#### Scenario: Trader 節點 schema 輸出
- **WHEN** API executor 跑到 Trader node
- **THEN** 內部呼叫 langchain `bind_structured(llm, TraderProposal)`,拿到 `TraderProposal` Pydantic 實例

### Requirement: API executor 不依賴新 MCP server 就可運作

`api` executor SHALL 在 dataflows MCP server 跟 decisions MCP server **都沒啟動**的情況下完整運作(向後相容既有部署)。SHALL 直接呼叫 `tradingagents/dataflows/interface.py` 既有 Python function。

#### Scenario: 無 MCP 環境跑 API mode
- **WHEN** 跑 `tradingagents analyze --executor api` 但兩個 MCP server 都沒啟動
- **THEN** propagate 完整跑完,行為跟現行 master 一致;`./reports/{TICKER}_{TIMESTAMP}/` 報告產生正常

### Requirement: API executor 可選走 dataflows MCP

當環境變數 `TRADINGAGENTS_DATAFLOWS_VIA_MCP=1` 設定且 dataflows MCP server 已啟動,API executor SHALL 透過 MCP client 呼叫 dataflows tool 而非直接呼 Python function。輸出語意 SHALL 跟直接呼叫一致(同 schema、同 fallback 行為)。

#### Scenario: 環境變數啟用 MCP routing
- **WHEN** 啟動 dataflows MCP server,跑 `TRADINGAGENTS_DATAFLOWS_VIA_MCP=1 tradingagents analyze --executor api SPY 2024-05-10`
- **THEN** Analyst node 的資料抓取走 MCP client,結果跟 `TRADINGAGENTS_DATAFLOWS_VIA_MCP=0` 跑同 ticker 同日期 byte-equivalent
