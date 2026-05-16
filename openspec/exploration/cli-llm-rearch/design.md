# Design — CLI-backed Executor Mode for TradingAgents

- **Created**: 2026-05-13
- **Author**: bzh889 (TradingAgents fork)
- **Status**: brainstorm complete, pending `/opsx:propose` to formalize as change
- **Brainstorm path**: this file is the output of `brainstorming` skill invoked via `/change-feature`
- **Reference handoff**: `openspec/exploration/handoff-tradingagents-2026-05-13/notes.md`
- **Codex consult**: 2026-05-13 session `019e1d27-7382-7bd0-a4e3-e2f26473f3e2` (full pushback recorded in §6)

---

## 1. Problem & goal

**Problem**: TradingAgents 目前一輪 propagate 要打 10-30 次 LLM API,token 成本累積很快;同時使用者已經付 Claude Code / Codex / Gemini CLI 訂閱費,可在這些 CLI 環境內直接呼叫同等級或更強的模型,還可以善用 CLI 內建的 subagent / Bash / Read / WebFetch 工具自主性。

**Goal**: 在現有 API 模式之外,**新增**一個訂閱制 CLI 執行模式,讓使用者跑 propagate 時可以從互動選單挑「用 API / 用 Claude Code / 用 Codex / 用 Gemini」。**API 模式零破壞**(現有 langchain 路徑全部保留),**LangGraph orchestration 不動**(節點順序、debate 輪次、structured output 結構都不動),CLI 模式跟 API 模式**寫入相同 persistence**(memory_log + checkpoint + reports)所以兩模式可互通(API run 留的 past_context,下次 CLI run 一樣讀得到)。

**Non-goal**: 不重做 LangGraph(不換 orchestrator)、不重寫 agent prompt、不換 dataflows 抓資料的邏輯、不做 Phase B reflection 改版、不動 cp950 stdout bug 修法(那是獨立 `/bugfix-incident`)。

---

## 2. Approach comparison

| 維度 | A. Codex MVP (建議的最小範圍) | B. 中間版 | **C. 本 design 選定** |
|---|---|---|---|
| CLI 粒度 | long-lived session,一個 propagate 一個 CLI | per-phase(5 階段 5 spawn) | **per-agent(每個 agent 一次 spawn)** |
| Persistence 變動 | 加 provenance fields(execution_mode / executor_version / cli_command / tool_versions / raw_artifact_path) | 加 execution_mode + raw_artifact_path | **完全不動,兩模式同檔同格式** |
| Dataflows MCP | 推遲到 second slice | 與 executor 同 PR | **與 executor 同 PR(一次 re-arch 一起上)** |
| Structured output | MCP `submit_decision` tool | 同 A | **同 A — MCP `submit_decision`** |
| Mid-flight fallback | 無(fail-closed) | 無 | **無(fail-closed at node boundary)** |
| Executor 抽象 | `NodeExecutor.run_node(state, spec) → NodeResult` | 同 | **同** |
| 首版執行器數量 | 1 個 CLI | 2-3 個 | **3 個(claude-code / codex / gemini)+ 既有 api** |
| 範圍預期 | 最小,可單一 PR | 中等 | **大,單一 /opsx:propose 多階段 tasks.md** |

**為什麼選 C**: 使用者明確要 day-one 完整支援(per-agent 粒度有獨立 log/cancel/audit 的便利、兩模式 persistence 必須兼容才能跨模式 reflection、dataflows MCP 同輪上才能讓 analyst node 在 CLI 模式也能抓資料)。Codex 反對的三點各有合理用意,但在這個專案脈絡下使用者優先序不同 — 詳見 §6 Risks accepted。

---

## 3. Architecture

### 3.1 New abstraction — `NodeExecutor`

新建 `tradingagents/executors/base.py`:

```python
from typing import Protocol
from dataclasses import dataclass
from .types import TradingState, NodeSpec, NodeResult, ExecutorError

class NodeExecutor(Protocol):
    """每個 graph node 在執行時委派給一個 executor。
    
    執行單位是「整個 node 的 state delta」,不是「一次 LLM chat completion」。
    這是抽象的關鍵 — CLI mode 不必假裝自己是 ChatModel。
    """
    name: str  # "api" / "claude-code" / "codex" / "gemini"

    def run_node(self, node_name: str, state: TradingState, spec: NodeSpec) -> NodeResult:
        ...

    def supports_structured(self) -> bool:
        """是否能透過 MCP tool 回 schema-validated 物件。
        api → True (langchain bind_structured)
        cli executors → True (透過 submit_decision MCP tool)
        """
        ...
```

`NodeSpec` 攜帶該 node 的:agent role、prompt template、可用 tools(dataflows MCP server URL)、schema(if any)、retry policy。`NodeResult` 是 `{state_delta: dict, raw_artifact_path: str | None, executor_metadata: dict}`。

### 3.2 Executor 實作

| 檔案 | 內容 |
|---|---|
| `executors/api.py` | 包現有 langchain 路徑(`llm_clients/` + `bind_structured`),`run_node` 就是現在 `agents/*/` 各 node 的程式碼搬一搬 |
| `executors/claude_code.py` | spawn `claude --print --output-format json` subprocess,prompt 帶 agent role + state + MCP config,parse JSON 出 tool call(submit_decision),驗 schema |
| `executors/codex.py` | spawn `codex exec --json -s read-only ...`,類似 |
| `executors/gemini.py` | spawn `gemini --json ...`(Gemini CLI 介面細節 implementation 階段確認) |

各 executor 內部可以髒(它們生命週期、permission model、transcript 格式都不一樣),只統一 `run_node` 介面。

### 3.3 Dataflows MCP server

新建 `tradingagents/dataflows/mcp_server.py`:

- 暴露 tools: `get_stock_data` / `get_indicators` / `get_fundamentals` / `get_news` / `get_global_news` / `get_insider_transactions` / `get_balance_sheet` / `get_cashflow` / `get_income_statement`
- 內部仍呼 `tradingagents/dataflows/interface.py` 的 routing(yfinance / alpha_vantage + fallback 鏈不動)
- 兩模式共用:
  - API mode:langchain ToolNode 用 MCP client 連這個 server(也可以選擇繼續直接呼 Python function,初版兩條都接)
  - CLI mode:executor 啟動 CLI 時 `--mcp-config` 指向這個 server

### 3.4 Decisions MCP server(獨立的)

新建 `tradingagents/decisions/mcp_server.py`:

- 暴露 tools: `submit_trader_proposal(qty, entry, exit, stop_loss, rationale)`、`submit_portfolio_decision(rating, allocation, rationale)`、`submit_rating(scale, value)`
- 參數即 Pydantic schema(沿用現有 `agents/utils/schemas.py` 內定義)
- CLI executor 看到 CLI 呼叫這個 tool 時,**抓出參數就是 schema-valid 結果**,不用 parse stdout markdown
- API mode 不用這個 server(它走 langchain `bind_structured` 直接拿 Pydantic),但 server 端的 schema 是同一份 — 兩條路 schema source of truth 不分裂

兩個 MCP server 在 CLI 啟動時都掛上去。

### 3.5 Selector(`cli/utils.py`)

互動選單改成兩階段:

```
Step 1: Execution mode
  > 1. API (langchain)
    2. Claude Code (subscription)
    3. Codex CLI (subscription)
    4. Gemini CLI (subscription)

Step 2 (conditional):
  If mode=API:
    沿用現有 10-provider 選單
  If mode=Claude Code / Codex / Gemini:
    確認 CLI 可呼叫(`which claude` / `codex --version` / `gemini --version`)
    讓使用者覆寫預設 model(可選)
```

### 3.6 Entry points

- **保留**: `tradingagents analyze [--checkpoint] [--clear-checkpoints]`(Typer)
- **新增**: `.claude/commands/trade.md` slash command,內容就是執行 `tradingagents analyze --executor <mode>` 並把 mode 參數預設為 `claude-code`。**這是 thin wrapper,不重複 orchestration**。CC session 跑這個 slash command 等同呼叫 Python 入口,只是預設 mode 不同。

### 3.7 Persistence(完全不動)

- `~/.tradingagents/memory/trading_memory.md` — append-only decision log,**兩模式同檔同格式**,沒有 execution_mode 區分
- `~/.tradingagents/cache/{ticker}/checkpoints/{TICKER}.db` — per-ticker SQLite,thread_id 計算不變
- `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/` — JSON state dumps
- `./reports/{TICKER}_{TIMESTAMP}/{1..5}_*/` — CLI 後寫的人讀報告

CLI mode 跑出來的 final_state 跟 API mode 跑出來的長一樣(同 TypedDict、同 keys、同 rating string),checkpoint resume 跨模式 OK。

### 3.8 Failure & resume

CLI mode 在任一 node 失敗(quota / timeout / parse / tool failure):
- LangGraph checkpoint 自動存到該 node 之前的狀態
- 顯示明確錯誤:`node bull_researcher failed: claude-code quota exhausted at 14:32`
- 使用者下次:`tradingagents analyze --resume --executor api`(或 `--executor codex` 換另一個 CLI)
- 從 checkpoint 接著跑,該 node 用新 executor 重做

**沒有自動 mid-flight fallback**(這跟 Codex 一致)。

---

## 4. Five trade-offs revisited

| # | 議題 | 決議 |
|---|---|---|
| Q1 | 委派粒度 | **Per-agent**(每個 LangGraph node 一次 CLI subprocess),Codex 反對見 §6.1 |
| Q2 | Tool 邊界 | **MCP push**(dataflows 包成 MCP server,兩模式共用)|
| Q3 | Structured output | **MCP `submit_decision` tool**(Codex 力挺,跟 dataflows MCP 同輪上)|
| Q4 | Parallelism | **預設 sequential**(per-agent 已經沒並行假設);若特定 phase(如 risk debate 3 個 debator)未來想平行,留給 v2 |
| Q5 | State / memory | **Memory log 當 prompt context 顯式注入**(沿用 `_resolve_pending_entries` 的 past_context),CLI session **不**自主 Read 該檔(reduce 不可控的 side effect) |

---

## 5. Animations Codex agreed with(納入 design)

- **Seam 不是 `ChatModel.invoke()` 等價物**,是 `run_node(state, spec) → NodeResult`(§3.1)
- **Provider 適配器內部各自髒,只統一一個 method**(§3.2)
- **MCP `submit_decision`** 是 structured output 唯一嚴肅解(§3.4)
- **Fail-closed at node boundary**,no auto mid-flight fallback(§3.8)
- **`/trade` thin wrapper**,不複製 orchestration(§3.6)
- **Two-stage selector**(execution mode → executor-specific config)(§3.5)
- **Windows encoding** 處理(§7)

---

## 6. Risks accepted (Codex 反對但使用者覆寫)

### 6.1 Per-agent 粒度的啟動成本

- **Codex 警告**: 一次 propagate 30-50 個 subprocess × 1-2s 啟動 = 30-100s 純啟動延遲,「flaky batch automation」
- **使用者選擇**: per-agent 保留,優先序是「每個 agent 獨立 log / 獨立 cancel / 獨立 audit」高於效能
- **接受的代價**: CLI mode propagate 預計比 API mode 慢 5-10x(實作後第一次 benchmark 才會有準數字)
- **緩解**: implementation phase 內留 hook,將來如要加「全局 session pool 重用 provider+model 相同的 CLI session」可以擴充 — 但 first slice **不做** session reuse(那會引入 context drift 與 state leak 風險)
- **驗證**: implementation 完成後跑一輪 API mode + 一輪 CLI mode 的 wallclock benchmark,寫進 spec acceptance criteria

### 6.2 Persistence 不加 provenance fields

- **Codex 警告**: 沒有 executor_version / cli_command / tool_versions 的 trading decision「replay/debug 形同垃圾」
- **使用者選擇**: 兩模式同檔同格式,長期跨模式 audit / reflection 的價值更大;provenance 不寫進 canonical memory log
- **緩解(本 design 額外加碼,跟 Codex 折衷)**: provenance 寫到**獨立的** per-run meta 檔 `./reports/{TICKER}_{TIMESTAMP}/_meta.json`(JSON,executor / cli_command / tool_versions / start_time / end_time / chunk count / token usage),不影響 memory_log 格式。canonical log 還是 mode-blind。
- **接受的代價**: 純靠 memory_log 看不出某條 decision 是 API 還是 CLI 產的;要 audit 該次 run 要去翻對應的 `_meta.json`。權衡:audit ad-hoc 可恢復、canonical 跨模式相容性優先。

### 6.3 Dataflows MCP 同一 PR 一起上(不分兩輪)

- **Codex 警告**: 「一次 re-arch 不要做兩個」,first slice 應該只證明 one CLI executor 能跑通 one graph
- **使用者選擇**: dataflows MCP 同 PR,initial CLI mode 要能跑 analyst node(否則 CLI mode 形同殘廢)
- **緩解**: tasks.md 把 dataflows MCP 切成獨立階段(可以單獨 review、單獨 merge);executor + selector 是 phase 1、dataflows MCP 是 phase 2、`submit_decision` MCP 是 phase 3、CLI executor 接這兩個 MCP 是 phase 4。同 spec、同 PR,但 phase-gated 可獨立驗證。
- **接受的代價**: spec 範圍更大,tasks.md 預估 50+ tasks(對比 Codex MVP 的 15-20 tasks);初版 ship 時間相應拉長

---

## 7. Cross-cutting concerns

### 7.1 Windows encoding(完整清單 — codex 補強過)

Subprocess spawn 環境必須設:
```python
env = {
    **os.environ,
    "PYTHONUTF8": "1",          # Python child 用 utf-8 stdout
    "PYTHONIOENCODING": "utf-8",
    "LANG": "C.UTF-8",          # 給 Node/Rust/Go CLI 看的
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",            # 砍 ANSI 控制字元
    "TERM": "dumb",             # 砍 spinner
}
```

stdout decode: `data.decode("utf-8", errors="replace")`。

**結構化結果不從 human stdout 解析** — 走 MCP tool call payload 或 result 檔案。stdout 只當 transcript 留檔。

### 7.2 Process lifecycle

- 每個 executor.run_node 開 subprocess 都用 context manager 保證 cleanup
- 超時 default 60s per node;超過 → `ExecutorError(reason="timeout")` → checkpoint 存
- subprocess crash(非零 exit code):collect stderr → 寫進 _meta.json → checkpoint 存

### 7.3 Subscription rate limit detection

- 各 CLI 回 quota error 的格式不同(claude-code "rate limit"、codex "401 quota"、gemini "429")
- Executor 內部各自偵測 quota / rate limit pattern → 統一回 `ExecutorError(reason="quota_exhausted")`
- LangGraph 看到 `QuotaError` 就 fail-closed,訊息明確

### 7.4 Determinism / replay

- Per-run 寫 `./reports/{TICKER}_{TIMESTAMP}/_meta.json` 含 executor / model / seed (若 CLI 支援) / start state hash
- `./reports/{TICKER}_{TIMESTAMP}/transcripts/{node_name}.{ext}` 留每個 node 的原始 transcript
- 真要 audit 一個歷史 decision:`memory_log` 拿 final state,`_meta.json` 拿 mode,`transcripts/` 拿原 input/output

---

## 8. Out of scope (明確列出避免 scope creep)

- **不修** `tradingagents/graph/trading_graph.py:323` 的 cp950 pretty_print bug — 那是獨立 `/bugfix-incident`(handoff notes §5.1 / D4)
- **不加** ruff / black / mypy / pre-commit(handoff notes D1)— re-arch 完成後另一個 `/safe-refactor`
- **不重組** `llm_clients/openai_client.py` 的 10-provider monolith(handoff notes D2)— API mode 完全不動是本 design 的承諾
- **不改** dataflows interface 的 yfinance / alpha_vantage routing 邏輯 — MCP server 只是包一層,內部不動
- **不做** memory log 結構升級 / TTL / 多使用者隔離(handoff notes Q4)— 另一個 design
- **不做** graph composability(handoff notes Q2)— 另一個 design
- **不支援** 在同一個 propagate 內**自動**混用 multiple executors —fail-closed 後使用者要明示切

---

## 9. Acceptance criteria(給 `/opsx:propose` 用)

1. `tradingagents analyze` 互動模式選 API → 行為跟現在**完全一樣**(diff regression 跑現有 108 tests + 42 subtests 全綠)
2. `tradingagents analyze` 選 Claude Code → 跑完一輪 SPY / 2024-05-10,輸出的 `final_state` 結構跟 API mode 一致(同 keys,rating ∈ {Buy/Overweight/Hold/Underweight/Sell})
3. CLI mode 跟 API mode 跑同一支 ticker 後,`~/.tradingagents/memory/trading_memory.md` 兩條紀錄格式相同、CLI 寫的可被下一次 API run 的 `_resolve_pending_entries` 正常讀到
4. CLI mode 中途 SIGINT → checkpoint 在當前 node 之前保存 → `--resume --executor api` 從該 node 繼續且能完成
5. `/trade SPY 2024-05-10` 在 Claude Code session 內呼叫成功(Equivalent to `tradingagents analyze --executor claude-code`)
6. Dataflows MCP server 跑得起來,`claude --mcp-config ... --print "get_stock_data SPY"` 能拿到資料
7. Decisions MCP server 跑得起來,`submit_portfolio_decision` schema validation 失敗的呼叫會回明確錯誤
8. Wallclock benchmark(SPY、analysts=all、debate_rounds=1):API mode T1 秒,CLI mode (Claude Code) T2 秒,文件中記錄 T2/T1 比例
9. Windows + 繁中 locale 上跑 CLI mode 不會撞 UnicodeDecodeError(stdout / stderr 都顯式 utf-8)
10. New tests: per-executor unit tests(mock subprocess 確認 prompt + env 正確),integration test(spawn 真 CLI 跑單一 node 並 assert NodeResult)

---

## 10. Hints for `/opsx:propose`

建議 tasks.md 切成 5 phase(per §6.3):

1. **Phase 1 — Executor abstraction**: `executors/base.py` + `executors/api.py`(包現有 langchain)+ 改 `graph/setup.py` 接受 executor 參數 + selector 新增 mode 階段。**完成後 API mode 路徑零變動**,108 tests 全綠當 baseline。

2. **Phase 2 — Decisions MCP**: `decisions/mcp_server.py` 暴露 schema tools。API mode 不依賴(它走 bind_structured)。本 phase 單獨可驗(CLI 手動呼叫 tool)。

3. **Phase 3 — Dataflows MCP**: `dataflows/mcp_server.py` 包現有 routing。API mode 沿用 ToolNode + Python function path。CLI mode 之後用 MCP。

4. **Phase 4 — Claude Code executor**: `executors/claude_code.py` 跑通 SPY 一輪;debug 主軸是 subprocess env / encoding / MCP wiring。

5. **Phase 5 — Codex + Gemini executors**: 沿用 phase 4 的 abstraction,各自一檔。`/trade` slash command 加進 `.claude/commands/`。

每個 phase 留 verify gate(該 phase 的 acceptance criteria 子集 + 跑 tests)後才進下一階段。

---

## 11. Open questions(留給 spec / implementation 階段)

- Q4 已決,但 implementation 階段要確認 Claude Code `--print --output-format json` 是否暴露 tool call,如果只暴露 final text → 退而求其次走 prompt+JSON+retry(備案,non-default)
- CLI session 啟動慢 + 訂閱 quota model 細節(Claude Code 每小時 / 每天 quota?Codex CLI 收費 model?) — implementation 前要 verify 各 CLI 的訂閱限制文件
- `/trade` slash command 在 Claude Code session 內被叫,**而本 propagate 又 spawn 出 child claude session 跑某個 node** — 巢狀 Claude Code session 是否被允許 / 是否計同一 quota?需 implementation 階段測
- Gemini CLI 是否有 MCP client 支援 — 若無,Gemini executor 走 prompt+JSON+retry,structured output 退化模式記在文檔

---

## 12. References

- Handoff assessment: `openspec/exploration/handoff-tradingagents-2026-05-13/notes.md` §5 risks / §6 debt / §7 open questions / §8 priorities
- Knowledge Tier 1 used:
  - `2026-04-12-orchestrator-state-passing-at-delegation-boundary.md` — §3.7/§3.8 explicit state pass
  - `2026-04-26-python-stdout-cp950-windows.md` — §7.1 完整 env 設定
  - `2026-04-21-skill-recommender-pattern.md` — §3.5 user-facing selector 設計
- Codex consult session `019e1d27-7382-7bd0-a4e3-e2f26473f3e2` — §5 同意點 / §6 反對點均出自此 session
