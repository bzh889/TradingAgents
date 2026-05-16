## 1. Phase 1 — Executor abstraction (API mode 路徑零破壞)

- [x] 1.1 建 `tradingagents/executors/__init__.py` (含 `resolve_executor()` factory)
- [x] 1.2 建 `tradingagents/executors/types.py`: `NodeSpec` (含 `_callable` shim per §D9)、`NodeResult`、`ExecutorError`
- [x] 1.3 建 `tradingagents/executors/base.py`: `NodeExecutor` `@runtime_checkable` Protocol
- [x] 1.4 建 `tradingagents/executors/api.py`: `APIExecutor` 透過 `NodeSpec._callable` shim delegate 給既有 agent fn,**零** agents 修改
- [x] 1.5 修改 `tradingagents/graph/setup.py`: 加 `executor: Optional[NodeExecutor] = None` 參數 + `_wrap_node_through_executor` 包每個 `create_*(llm)` 回的 callable;預設 APIExecutor()
- [x] 1.6 修改 `tradingagents/graph/trading_graph.py`: `__init__` 加 `executor: str | NodeExecutor = "api"`;透過 `resolve_executor()` 解析;傳進 GraphSetup
- [x] 1.7 修改 `cli/utils.py`: 加 `select_execution_mode()` + `EXECUTION_MODES` 表;非 api 模式顯示 phase 4/5 「coming soon」訊息並 re-prompt
- [x] 1.8 修改 `cli/main.py` `analyze` 指令: 加 `--executor` typer flag;有設則 `resolve_executor` 先驗證再 pass 給 run_analysis;run_analysis 沒設則 prompt
- [-] 1.9 修改 `main.py` 範例: **skip** — TradingAgentsGraph executor 預設 "api" 已涵蓋向後相容;main.py 範例維持原樣即合法 API mode
- [x] 1.10 在 `tests/test_node_executor_contract.py` 加 12 test (types/Protocol/APIExecutor 契約 + module exports)
- [x] 1.11 在 `tests/test_graph_executor_param.py` 加 9 test (GraphSetup/TradingAgentsGraph signature + resolve_executor 行為 + `_wrap_node_through_executor`)
- [x] 1.12 **Phase 1 verify gate**: `pytest -q` 全綠 — **129 passed, 1 third-party warning, 42 subtests passed** (108 baseline + 21 新 = 129);所有 import 路徑通;CLI flag `--executor` typer help 顯示正常
- [ ] 1.13 commit phase 1 (commit msg: `feat(executor-mode-selection,api-executor): add NodeExecutor abstraction, wrap existing langchain as api executor`)

## 2. Phase 2 — Decisions MCP server

- [x] 2.1 加 `mcp>=1.0.0` 依賴到 `pyproject.toml`;`uv sync` 驗證安裝 mcp 1.27.1;順手加 `[dependency-groups] dev` 含 `pytest>=9.0.3` + `pytest-subtests>=0.15.0` (uv sync 預設只裝 main deps,沒這段 dev 工具會被移掉)
- [x] 2.2 建 `tradingagents/decisions/__init__.py` 暴露 `submit_research_plan` / `submit_trader_proposal` / `submit_portfolio_decision`
- [x] 2.3 schemas 確認:`tradingagents/agents/schemas.py` 已有 `ResearchPlan` / `TraderProposal` / `PortfolioDecision` + 對應 `PortfolioRating` / `TraderAction` enum;decisions 模組直接 import,**不重新定義**
- [x] 2.4 建 `tradingagents/decisions/mcp_server.py`: 用 `mcp.server.fastmcp.FastMCP` 包 3 個 tool;lazy import (SDK 不在時模組仍可 import,server 不啟);各 tool 的參數**對應 schema 真實欄位**(spec drift correction,記錄 design §D10):`submit_research_plan(recommendation, rationale, strategic_actions)` / `submit_trader_proposal(action, reasoning, entry_price?, stop_loss?, position_sizing?)` / `submit_portfolio_decision(rating, executive_summary, investment_thesis, price_target?, time_horizon?)`
- [x] 2.5 加 `tests/test_decisions_submission.py` 15 test: 模組 exports、3 個 submit fn happy path、缺必填 reject、enum 不合法 reject、Trader 的 Overweight reject (鎖 3-tier vs 5-tier 邊界)、mcp_server 模組可 import + 暴露 3 個 handler
- [-] 2.6 README: **skip** — phase 4 接 claude-code executor 時加(那時才有真正使用者),phase 2 module-level docstring 已足
- [x] 2.7 **Phase 2 verify gate**: `pytest -q` 全綠 **144 passed (129 baseline + 15 new) + 42 subtests + 1 third-party warning**;`from tradingagents.decisions.mcp_server import _build_server; s = _build_server()` 回 FastMCP instance(name="tradingagents-decisions"),確認 SDK 接通可建 server
- [ ] 2.8 commit phase 2 (commit msg: `feat(decisions-mcp): expose schema-validated submit tools via MCP server`)

## 3. Phase 3 — Dataflows MCP server

- [x] 3.1 建 `tradingagents/dataflows/mcp_server.py`: 9 個 module-level tool handler(`get_stock_data`、`get_indicators`、`get_fundamentals`、`get_balance_sheet`、`get_cashflow`、`get_income_statement`、`get_news`、`get_global_news`、`get_insider_transactions`),簽名對齊既有 `agents/utils/*_tools.py` @tool wrapper;每個 handler 直接呼 `route_to_vendor(method_name, ...)`
- [x] 3.2 Tool handler 直接呼 `tradingagents.dataflows.interface.route_to_vendor(...)` — 一行轉發,不動 routing 邏輯;`TOOL_NAMES` tuple 鎖 9 個名字讓 spec test 可驗
- [x] 3.3 加 `tests/test_dataflows_mcp.py` 11 test: 模組 exports + `_build_server()` 回 FastMCP(name=tradingagents-dataflows) + 每個 tool 透過 mock 確認 `route_to_vendor("<method>", ...)` 被以正確 args 呼叫;`get_global_news` optional args 兩變體都通
- [x] 3.4 在 `tests/test_dataflows_mcp.py::TestDataflowsToolsReadOnly` 直接 assert `TOOL_NAMES` 全 9 個都不含 `set_/write_/delete_/update_/post_/put_` 前綴 + tool 計數 lock 在 9(spec 變動同步)
- [-] 3.5 env var gate `TRADINGAGENTS_DATAFLOWS_VIA_MCP`: **移到 Phase 4**(claude-code executor 真正用到 MCP-via-subprocess 才需要,Phase 3 server 自己 standalone 已可驗)
- [-] 3.6 `test_api_executor_via_mcp.py`: **移到 Phase 4**(配套 3.5)
- [-] 3.7 dataflows README: **skip**(同 phase 2 decisions README — 等 phase 4 真正使用者出現時再寫)
- [x] 3.8 **Phase 3 verify gate**: `pytest -q` 全綠 **155 passed (144 baseline + 11 new) + 42 subtests + 1 third-party warning**;`_build_server()` 回 FastMCP(name=tradingagents-dataflows);phase 1/2 既有 tests 仍綠
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
