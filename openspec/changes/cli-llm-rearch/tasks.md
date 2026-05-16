## 1. Phase 1 — Executor abstraction (API mode 路徑零破壞)

- [ ] 1.1 建 `tradingagents/executors/__init__.py`
- [ ] 1.2 建 `tradingagents/executors/types.py`: 定義 `TradingState`(沿用 `agents/utils/agent_states.py` 的 TypedDict 重新匯出)、`NodeSpec`(`agent_role: str`、`prompt_template: str`、`tools: list[str]`、`schema: type[BaseModel] | None`、`retry_policy: dict`)、`NodeResult`(`state_delta: dict`、`raw_artifact_path: str | None`、`executor_metadata: dict`)、`ExecutorError(reason, node, raw_error)`
- [ ] 1.3 建 `tradingagents/executors/base.py`: `NodeExecutor` Protocol(`name: str`、`run_node(node_name, state, spec) -> NodeResult`、`supports_structured() -> bool`)
- [ ] 1.4 建 `tradingagents/executors/api.py`: 包現有 langchain 邏輯,`APIExecutor` 實作 `NodeExecutor`;`run_node` 內部呼叫現有 `create_llm_client(...)` 並執行該 node 的工作(從 `agents/*/` 抽出 node-level prompt+invoke 邏輯,但**不動** `agents/*/` 檔)
- [ ] 1.5 修改 `tradingagents/graph/setup.py`: 每個 node factory 接受 `executor: NodeExecutor = APIExecutor()` 參數(預設 API 確保零破壞);node 內 chat completion 改呼 `executor.run_node(...)`;非 chat 部分(state mutation、tool node 觸發)維持不動
- [ ] 1.6 修改 `tradingagents/graph/trading_graph.py`: `TradingAgentsGraph.__init__` 多吃 `executor: NodeExecutor | str = "api"` 參數;若是 str 則用 factory 解析成 executor 實例;傳進 `GraphSetup.setup_graph(...)`
- [ ] 1.7 修改 `cli/utils.py` 互動選單為兩段式: 抽 `select_execution_mode()` 函式(回 `"api"/"claude-code"/"codex"/"gemini"`);保留 `select_llm_provider()` 等既有函式,在 mode=api 時呼叫;mode=claude-code/codex/gemini 時 phase 1 stub 顯示 `(coming soon — Phase 4+)` 並退回 Step 1
- [ ] 1.8 修改 `cli/main.py` `analyze` 指令: 加 `--executor {api,claude-code,codex,gemini}` flag(default 不設,進互動式;有設則跳過 Step 1)
- [ ] 1.9 修改 `main.py` 範例: 在 `config.copy()` 之後加 `config["executor"] = "api"` 範例註解(或不動 main.py,executor 預設值處理掉)
- [ ] 1.10 在 `tests/` 加 `test_api_executor.py`: assert `APIExecutor` 實作 `NodeExecutor` Protocol;mock LLM 跑一個 analyst node,確認 `NodeResult.state_delta` 含 `market_report` key
- [ ] 1.11 在 `tests/` 加 `test_graph_executor_param.py`: assert `TradingAgentsGraph(executor="api")` 跟 `TradingAgentsGraph()` 行為一致;assert 傳 invalid executor name raises clear error
- [ ] 1.12 **Phase 1 verify gate**: 跑 `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q` — 既有 108 tests + 42 subtests 全綠 + 新增 2 個 test files 也綠;跑 `tradingagents analyze SPY 2024-05-10 --executor api`(以 mock 確保 deterministic)的 final_state diff vs phase 0 baseline = 0
- [ ] 1.13 commit phase 1 (commit msg: `feat(executor-mode-selection,api-executor): add NodeExecutor abstraction, wrap existing langchain as api executor`)

## 2. Phase 2 — Decisions MCP server

- [ ] 2.1 加依賴 `mcp` (或 `fastmcp`) 到 `pyproject.toml`,跑 `uv sync` 驗證 lockfile
- [ ] 2.2 建 `tradingagents/decisions/__init__.py`
- [ ] 2.3 識別並從 `agents/utils/schemas.py`(或對應位置)取得既有 `TraderProposal`、`PortfolioDecision`、`Rating` Pydantic schema;若沒集中於該檔,在 `tradingagents/decisions/schemas.py` 重新 export 但**不複製定義**(import 既有)
- [ ] 2.4 建 `tradingagents/decisions/mcp_server.py`: 用 mcp SDK 建立 server,暴露 3 個 tool — `submit_trader_proposal(qty, entry, exit, stop_loss, rationale)`、`submit_portfolio_decision(rating, allocation, rationale)`、`submit_rating(scale, value)`;每個 tool 從對應 Pydantic schema 自動生成 MCP tool schema;tool handler 為 schema-valid 接收 + return-validated-value(不執行其他副作用)
- [ ] 2.5 加 `tests/test_decisions_mcp.py`: 啟動 server in-process,呼叫 `submit_portfolio_decision(rating="Buy", allocation=0.5, rationale="test")` 成功;呼叫 `submit_portfolio_decision(rating="Buy")` 缺欄位被 reject 並回明確錯誤;呼叫 `submit_rating(scale="invalid", value="x")` 拒絕並列出合法 scale
- [ ] 2.6 加 README section 或 `tradingagents/decisions/README.md`: 文件啟動指令 `python -m tradingagents.decisions.mcp_server`,以及 stdio / TCP transport 設定
- [ ] 2.7 **Phase 2 verify gate**: phase 2 新增 test 全綠;手動跑 `python -m tradingagents.decisions.mcp_server` 啟動成功;從另一終端用 mcp client 跑 `list_tools` 看到 3 個 tool;phase 1 既有 tests 仍綠
- [ ] 2.8 commit phase 2 (commit msg: `feat(decisions-mcp): expose schema-validated submit tools via MCP server`)

## 3. Phase 3 — Dataflows MCP server

- [ ] 3.1 建 `tradingagents/dataflows/mcp_server.py`: 用 mcp SDK 建立 server,暴露 9 個 tool — `get_stock_data`、`get_indicators`、`get_fundamentals`、`get_news`、`get_global_news`、`get_insider_transactions`、`get_balance_sheet`、`get_cashflow`、`get_income_statement`;每個 tool 簽名跟 `dataflows/interface.py` 對應函式對齊(param names + types + defaults)
- [ ] 3.2 Tool handler 內部直接 `from tradingagents.dataflows.interface import get_stock_data as _get_stock_data` 等;handler 只做 schema 接收 + 呼 _get_stock_data + return,**不動** interface.py 的 routing 邏輯
- [ ] 3.3 加 `tests/test_dataflows_mcp.py`: 啟動 server in-process,呼叫 `get_stock_data(ticker="SPY", date="2024-05-10", vendor="yfinance")` 成功取得資料;呼叫 `get_stock_data(ticker="SPY", date="2024-05-10")` 不指定 vendor 用預設 yfinance;模擬 yfinance hit rate-limit 確認 fallback 切到 alpha_vantage(用 monkeypatch 注入)
- [ ] 3.4 加 `tests/test_dataflows_mcp_readonly.py`: `list_tools` 確認 9 個 tool 名都不含 `set_` / `write_` / `delete_` / `update_` 前綴
- [ ] 3.5 修改 `tradingagents/executors/api.py`: 加環境變數 gate `TRADINGAGENTS_DATAFLOWS_VIA_MCP=1` 切走 MCP client 路徑(預設不開,沿用直接 Python function call);MCP client wrapper 取相同 fn(ticker, date, vendor)介面
- [ ] 3.6 加 `tests/test_api_executor_via_mcp.py`: 設環境變數跑單一 analyst node,assert 結果跟不設變數時一致
- [ ] 3.7 加 `tradingagents/dataflows/README.md` 或更新既有: 文件 MCP server 啟動方式跟 `TRADINGAGENTS_DATAFLOWS_VIA_MCP=1` 切換
- [ ] 3.8 **Phase 3 verify gate**: phase 3 新增 test 全綠;`python -m tradingagents.dataflows.mcp_server` 啟動成功;phase 1+2 既有 tests 仍綠;`TRADINGAGENTS_DATAFLOWS_VIA_MCP=1 tradingagents analyze --executor api SPY 2024-05-10` 跟未設環境變數版本 byte-equivalent final_state(以 schema 比較)
- [ ] 3.9 commit phase 3 (commit msg: `feat(dataflows-mcp): expose dataflows routing as MCP server, share between api and cli mode`)

## 4. Phase 4 — Claude Code executor (第一個 CLI executor)

- [ ] 4.1 **Smoke test 巢狀 Claude Code session**: 在 Claude Code session 跑 `claude --print "say hello"` subprocess;確認 (a) 是否成功 (b) sandbox 是否阻擋 (c) token usage 是否疊算;結果寫到 `tradingagents/executors/CLAUDE_CODE_NESTING_NOTES.md`。若巢狀不可行,Phase 5 `/trade` slash command 改強制 `--executor api`
- [ ] 4.2 建 `tradingagents/executors/claude_code.py`: `ClaudeCodeExecutor` 實作 `NodeExecutor`
- [ ] 4.3 在 `claude_code.py` 內 `run_node`: 構造 prompt(agent_role + state injection + tools 描述);spawn `subprocess.Popen(["claude", "--print", "--output-format", "json", "--mcp-config", <generated>], ...)`;傳完整 utf-8 env override:
  ```python
  env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
         "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
         "NO_COLOR": "1", "TERM": "dumb"}
  ```
  stdin/stdout/stderr 用 `subprocess.PIPE` 配 `text=False`;decode 用 `output.decode("utf-8", errors="replace")`
- [ ] 4.4 Parse Claude Code JSON stream: 抽取 `tool_use` events,過濾出 decisions MCP tool calls(`submit_trader_proposal` / `submit_portfolio_decision` / `submit_rating`);取 tool call 參數作為 schema-valid `NodeResult.state_delta`
- [ ] 4.5 動態生成 mcp-config: 含 dataflows MCP server URL + decisions MCP server URL,寫入 temp file 傳給 `claude --mcp-config <tmpfile>`;teardown 時 cleanup temp
- [ ] 4.6 實作 timeout 機制: default 60s per node(可用 NodeSpec.retry_policy 覆寫);超時 kill subprocess 回 `ExecutorError(reason="timeout", node=<node_name>)`
- [ ] 4.7 實作 quota / rate-limit 偵測: parse stderr / JSON error events 找 "rate limit" / "quota" / "401" 訊號;統一回 `ExecutorError(reason="quota_exhausted", raw_error=<original>)`
- [ ] 4.8 實作 fail-closed: catch `ExecutorError` 在 LangGraph node 內 raise;不重試、不切 executor;LangGraph checkpoint 自動存當前 state
- [ ] 4.9 修改 `cli/utils.py`: Step 1 「Claude Code」選項從 stub 變實作 — 跑 `which claude` 驗證 PATH,顯示版本(`claude --version`),讓使用者可選覆寫 model 跟 backend_url
- [ ] 4.10 修改 `cli/main.py`: 啟動 claude-code executor 前自動 spawn dataflows + decisions MCP server(child process),teardown 時 cleanup
- [ ] 4.11 新增 per-run meta 寫入: `./reports/{TICKER}_{TIMESTAMP}/_meta.json` 含 `execution_mode`、`executor_version`、`cli_command`(包 sanitize 過的 args)、`tool_versions`(claude / python / mcp SDK)、`start_time`、`end_time`、`chunk_count`、`token_usage`、`transcripts[]` 每個 node 的 transcript 檔路徑
- [ ] 4.12 新增 transcript 落地: `./reports/{TICKER}_{TIMESTAMP}/transcripts/{node_name}.jsonl` 每個 CLI subprocess 的 stdout/stderr raw 落地;檔尾保留 raw,前面加 metadata header
- [ ] 4.13 加 `tests/test_claude_code_executor.py`: mock subprocess(monkeypatch `subprocess.Popen`)assert env 帶完整 utf-8 設定;assert tool call payload 被取出當 state_delta;assert timeout 觸發 ExecutorError;assert quota 訊號被識別
- [ ] 4.14 加 `tests/test_persistence_cross_mode.py`: 第一輪 SPY 用 `api` mode 跑完,第二輪 SPY 用 `claude-code` mode 跑(mock subprocess output 模擬合理回應);assert 第二輪的 `_resolve_pending_entries` 讀得到第一輪寫的 memory log entry;assert memory_log 兩條 entry 格式相同(無 execution_mode field)
- [ ] 4.15 **Phase 4 verify gate**: phase 4 新增 test 全綠;phase 1+2+3 既有 tests 仍綠;`tradingagents analyze SPY 2024-05-10 --executor claude-code`(真實 CLI)跑出來的 final_state 結構跟 API mode 一致(同 keys、rating ∈ {Buy/Overweight/Hold/Underweight/Sell});Windows + 繁中 locale 跑不撞 UnicodeError;`_meta.json` 寫入正確;wallclock benchmark 紀錄 API vs CLI 時間比例
- [ ] 4.16 commit phase 4 (commit msg: `feat(cli-executor): claude-code subprocess executor with MCP wiring, utf-8 env, fail-closed quota detection`)

## 5. Phase 5 — Codex + Gemini executor + `/trade` slash command

- [ ] 5.1 建 `tradingagents/executors/codex.py`: `CodexExecutor` 實作 `NodeExecutor`,subprocess 呼叫 `codex exec --json -s read-only --mcp-config <config> "<prompt>"`,JSON stream 解析參考 `~/.claude/skills/codex/SKILL.md` Python parser pattern;quota / timeout / fail-closed 處理同 ClaudeCodeExecutor
- [ ] 5.2 加 `tests/test_codex_executor.py` 對應 phase 4.13 test pattern
- [ ] 5.3 建 `tradingagents/executors/gemini.py`: `GeminiExecutor`;先 verify Gemini CLI 是否支援 MCP(`gemini --help` 找 mcp flag);若支援走 decisions MCP path,若不支援 fallback 為 prompt + JSON parse + 最多 2 次 retry
- [ ] 5.4 加 `tests/test_gemini_executor.py`: 兩條 path 都測 — MCP path 跟 JSON fallback path
- [ ] 5.5 修改 `cli/utils.py`: Step 1 「Codex」「Gemini」選項從 stub 變實作(verify CLI 在 PATH、顯示版本、覆寫 model)
- [ ] 5.6 建 `.claude/commands/trade.md`: 內容 prompt Claude Code session 執行 `tradingagents analyze --executor claude-code <args>`(若 task 4.1 結果顯示巢狀不可行,改為 `--executor api`);文件含 invocation 範例 `/trade SPY 2024-05-10`、`/trade SPY 2024-05-10 --executor codex`,以及巢狀 session 行為說明
- [ ] 5.7 加 `tests/test_trade_slash_command.py`: assert trade.md 存在;assert 內容包含「`tradingagents analyze --executor`」;若 task 4.1 結果可巢狀,assert 內容含「`--executor claude-code`」當預設
- [ ] 5.8 **Phase 5 verify gate**: phase 5 新增 test 全綠;三個 CLI executor 各跑通一輪 SPY/2024-05-10;`/trade SPY 2024-05-10` 在 Claude Code session 內呼叫成功且行為跟 `tradingagents analyze --executor <default>` 一致;Acceptance criteria 完整對齊(design §9 10 條全部 PASS)
- [ ] 5.9 commit phase 5 (commit msg: `feat(cli-executor,trade-slash-command): add codex and gemini executors, /trade slash command`)

## 6. Documentation & Cleanup

- [ ] 6.1 更新 `README.md`: 在「CLI Usage」段加 execution mode 說明;在「Required APIs」段加訂閱制 CLI 說明(claude / codex / gemini install 連結)
- [ ] 6.2 更新 `CHANGELOG.md`: 加 `[Unreleased]` 段含 4 個 CLI executor、2 個 MCP server、2 段式選單、`/trade` slash command 主要 bullets
- [ ] 6.3 更新 `tradingagents/__init__.py` 若有版本字串: bump version
- [ ] 6.4 跑 `openspec validate cli-llm-rearch` 確認 spec 結構合法
- [ ] 6.5 跑 `openspec instructions apply --change cli-llm-rearch --json` 確認 contextFiles 列出正確
- [ ] 6.6 在 PR 描述含 design §6 三個使用者 override Codex 反對的點(per-agent 粒度 / persistence 不動 / dataflows MCP 同輪)當「decisions to scrutinize during review」

## 7. Final integration verify

- [ ] 7.1 完整跑 `pytest -q` 全綠
- [ ] 7.2 跑 `tradingagents analyze SPY 2024-05-10 --executor api` 行為跟 master 一致
- [ ] 7.3 跑 `tradingagents analyze SPY 2024-05-10 --executor claude-code` 跑完且 final_state schema 對齊
- [ ] 7.4 跑 `tradingagents analyze SPY 2024-05-10 --executor codex` 跑完
- [ ] 7.5 跑 `tradingagents analyze SPY 2024-05-10 --executor gemini` 跑完
- [ ] 7.6 跑 `/trade SPY 2024-05-10` 在 Claude Code 內成功
- [ ] 7.7 Cross-mode reflection 驗證: 第一輪 api → 第二輪 claude-code → assert `_resolve_pending_entries` 跨模式讀寫互通
- [ ] 7.8 Acceptance criteria 全部 PASS(對照 design §9 10 條,每條附驗證指令 + 預期輸出)
