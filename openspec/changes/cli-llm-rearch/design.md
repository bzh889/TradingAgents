## Context

TradingAgents 是用 LangGraph 編排多個 LLM agent(analyst → bull/bear debate → trader → risk debate → portfolio manager)做股票買賣決策的研究框架,Python ≥ 3.10,4861 行套件程式碼 + 1739 行 CLI。現況經由 langchain 對 10 個 LLM provider(OpenAI/Anthropic/Google/Azure/xAI/DeepSeek/Qwen/GLM/OpenRouter/Ollama/NVIDIA NIM)直接呼叫 API 來執行每個 agent 的工作,每輪 propagate 累積 10-30 次 API call,token 成本可觀。

使用者已經付 Claude Code / Codex / Gemini CLI 訂閱費,訂閱配額內呼叫對相同等級或更強模型零邊際成本。同時這些 CLI 內建 Bash / Read / Web / subagent 等工具,在合適粒度委派下可讓 agent 有更高自主性。本改造引進 per-node CLI executor,使用者於互動式選單選擇執行模式;API mode 完全保留作為 baseline。

完整 brainstorm 過程與決策歷史: `openspec/exploration/cli-llm-rearch/design.md`(18 KB,12 sections,含 Codex 對抗式 consult session `019e1d27-7382-7bd0-a4e3-e2f26473f3e2` 的反對點與使用者覆寫紀錄)。本檔是該設計的 OpenSpec-canonical 版本。

## Goals / Non-Goals

**Goals:**

- 新增 4 個可互換的 NodeExecutor: `api`(包現有 langchain)/ `claude-code` / `codex` / `gemini`
- LangGraph orchestration 不動 — StateGraph、node 順序、debate 輪次、structured output 結構都不變
- 互動選單由「選 provider」升級成兩段「選 execution mode → 選 provider/executor config」
- CLI executor 跑 schema-validated 輸出(TraderProposal / PortfolioDecision / Rating)走 MCP `submit_decision` 工具,不走 markdown regex parsing
- Dataflows 包成 MCP server,API mode 跟 CLI mode 共用單一資料源,routing(yfinance / alpha_vantage + fallback)邏輯不動
- 兩模式寫入完全相同的 persistence 路徑跟格式,跨模式 reflection 可互通(API run 寫的 memory log,下次 CLI run 一樣讀得到)
- 第二個入口: `.claude/commands/trade.md` slash command(thin wrapper 呼叫 `tradingagents analyze`),讓 Claude Code session 內直接呼叫 trading 流程
- 既有 108 tests + 42 subtests 跑 API mode 必須完全綠(regression baseline)

**Non-Goals:**

- 不重寫 LangGraph orchestrator(graph 結構、edge、conditional routing 都不動)
- 不重寫 agent prompt(`tradingagents/agents/**` 全部不動)
- 不重組 `tradingagents/llm_clients/openai_client.py` 10-provider monolith(handoff notes D2,延後處理)
- 不修 `tradingagents/graph/trading_graph.py:323` cp950 pretty_print bug(handoff notes D4,獨立 `/bugfix-incident`)
- 不加 ruff / black / mypy / pre-commit(handoff notes D1,獨立 `/safe-refactor`)
- 不改 dataflows interface 的 yfinance / alpha_vantage routing 邏輯
- 不做 memory log schema 升級 / TTL / 多使用者隔離(handoff notes Q4)
- 不做 graph composability(讓使用者自組 graph,handoff notes Q2)
- 不支援同一 propagate 內**自動**混用多個 executor — fail-closed 後使用者必須明示切

## Decisions

### D1 — Seam 抽象: `NodeExecutor.run_node(state, spec) → NodeResult`

把替換點放在 LangGraph **node 執行邊界**,不放在 ChatModel.invoke 邊界。各 executor 的執行模型(sync chat completion / long-running subprocess / autonomous agent session)差異大,假裝它們都是 ChatModel 會漏抽象。

```python
# tradingagents/executors/base.py
from typing import Protocol
from .types import TradingState, NodeSpec, NodeResult

class NodeExecutor(Protocol):
    name: str  # "api" / "claude-code" / "codex" / "gemini"
    def run_node(self, node_name: str, state: TradingState, spec: NodeSpec) -> NodeResult: ...
    def supports_structured(self) -> bool: ...
```

`NodeSpec` 帶: agent role、prompt template、可用 tools(dataflows MCP URL)、schema(if any)、retry policy。
`NodeResult` = `{state_delta: dict, raw_artifact_path: str | None, executor_metadata: dict}`。

**Rationale**: Codex consult 明確指出這個 seam shape — 各 CLI 自己內部髒沒關係,介面只統一 run_node。Alternative(統一在 ChatModel 介面)會強迫 CLI 假裝同步、限縮 CLI 的 autonomy 優勢,被淘汰。

### D2 — Per-agent CLI 粒度

每個 LangGraph node 在 CLI mode 下都 spawn 一次 subprocess 跑該 agent 的工作。

**Rationale**: 使用者 explicit override Codex 的建議(Codex 主張 per-phase 或 long-lived session,30-100s subprocess 啟動成本太重)。使用者優先序: 每個 agent 獨立 log / 獨立 cancel / 獨立 audit 比單次 propagate 延遲短重要。

**Alternatives 考慮過**:
- Per-phase (5 階段 5 spawn,Codex 提案) — 啟動成本降 90% 但每個 phase 內失敗 cancel 變模糊
- Long-lived session(整個 propagate 一個 CLI,Codex MVP)— 最省啟動但 context drift / state leak 風險高,trace 難拆
- Per-agent + session pool(模型相同就重用)— D2 v2 可考慮,**first slice 不做**(避免 context drift bug)

**接受代價**: CLI mode 預計比 API mode 慢 5-10x(per-agent × 1-2s 啟動 × 30-50 node)。Acceptance criterion 9 要求測 wallclock 並紀錄比例。

### D3 — 結構化輸出走 MCP `submit_decision` 工具

`tradingagents/decisions/mcp_server.py` 暴露三個 submit tools,參數**直接對應**既有 `tradingagents/agents/schemas.py` 的 Pydantic 欄位(不重新定義):

| Tool | 對應 schema | 參數 (從 schemas.py 真實欄位) |
|---|---|---|
| `submit_research_plan` | `ResearchPlan` | `recommendation` (PortfolioRating enum), `rationale`, `strategic_actions` |
| `submit_trader_proposal` | `TraderProposal` | `action` (TraderAction enum), `reasoning`, `entry_price?`, `stop_loss?`, `position_sizing?` |
| `submit_portfolio_decision` | `PortfolioDecision` | `rating` (PortfolioRating enum), `executive_summary`, `investment_thesis`, `price_target?`, `time_horizon?` |

CLI executor 呼這些 tool 時直接拿 schema-valid 物件(或 schema error)。完全不依賴 stdout markdown parsing。**Phase 2 brainstorm 寫的「qty/entry/exit」是占位字面,Phase 2 implementation 開工讀 schemas.py 後對齊到真實欄位**(spec drift correction,記錄於 §D10)。

**Rationale**: Codex 強烈推薦,符合 D5 dataflows MCP 同輪上的整體方向(反正 MCP server 必須架,多一個 decisions server 邊際成本低)。Heuristic regex 已被 Codex 評為「unserious」。Prompt+JSON+retry 留作 fallback(implementation 階段若發現某 CLI 不支援 MCP tool call,才退而求其次)。

**API mode 不用 decisions MCP**: 它走 langchain `bind_structured(llm, schema)` 直接拿 Pydantic。但 schema source of truth 是同一份(`agents/utils/schemas.py`),decisions MCP server 直接 import 該模組,兩條路不分裂。

### D4 — Dataflows 包成 MCP server,API mode 跟 CLI mode 共用

`tradingagents/dataflows/mcp_server.py` 暴露 `get_stock_data` / `get_indicators` / `get_fundamentals` / `get_news` / `get_global_news` / `get_insider_transactions` / `get_balance_sheet` / `get_cashflow` / `get_income_statement`。內部呼叫現有 `dataflows/interface.py` routing(yfinance + alpha_vantage + fallback 不動)。

兩模式共用:
- API mode: 初版 langchain ToolNode 可選(a) 沿用直接 Python function call(b) 改走 MCP client。兩條都接保險。
- CLI mode: executor 啟動 CLI 時 `--mcp-config` 指向這個 server

**Rationale**: 使用者 explicit override Codex 的「dataflows MCP 推延 second slice」建議。理由是 CLI mode 初版必須能跑 analyst node(那些 node 必須抽資料),若 dataflows MCP 不同輪上,CLI mode 等於殘廢(只能跑 researcher / trader / PM 等純推理 node)。代價是 spec 範圍變大,tasks.md 用 phase-gated 切法緩解(見 §Migration Plan)。

### D5 — 兩段式互動選單

`cli/utils.py` 現有單一階段(選 LLM provider)改成兩段:

```
Step 1: Execution mode
  1. API (langchain)
  2. Claude Code (subscription)
  3. Codex CLI (subscription)
  4. Gemini CLI (subscription)

Step 2 (conditional on Step 1 選擇):
  If mode=API: 沿用現有 10-provider 選單(零改動)
  If mode=CLI executor:
    驗證 CLI 在 PATH (`which claude` / `codex --version` / `gemini --version`)
    讓使用者覆寫預設 model(可選)
    讓使用者覆寫 backend_url(NIM 走這條的特殊情境)
```

**Rationale**: 既有選單就是「選一個 provider」,擴成「選 mode → 選 provider 設定」是最小破壞的擴展。Codex agreed。

### D6 — Persistence 完全不動 + per-run `_meta.json` 補 provenance

Persistence 路徑跟格式**不變**:
- `~/.tradingagents/memory/trading_memory.md`(append-only decision log,兩模式同檔同格式,**沒有** execution_mode 區分 field)
- `~/.tradingagents/cache/{ticker}/checkpoints/{TICKER}.db`(per-ticker SQLite checkpointer)
- `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/`(JSON state dumps)
- `./reports/{TICKER}_{TIMESTAMP}/{1..5}_*/`(CLI 後寫的人讀報告,5 個 phase 子目錄)

**新增** per-run meta(獨立檔,不影響上面):
- `./reports/{TICKER}_{TIMESTAMP}/_meta.json` — 記 `execution_mode` / `executor_version` / `cli_command` / `tool_versions` / `start_time` / `end_time` / `chunk_count` / `token_usage` / 每個 node 的 transcript 路徑
- `./reports/{TICKER}_{TIMESTAMP}/transcripts/{node_name}.{ext}` — 每個 node 原始 transcript(API mode 是 langchain run trace、CLI mode 是 subprocess stdout/stderr)

**Rationale**: 使用者 explicit override Codex 的「persistence 必須加 provenance fields」建議。優先序: 兩模式同檔長期跨模式 audit 可互通(canonical memory_log mode-blind)。代價: 純看 memory_log 看不出某條 decision 是哪種 mode 跑出來;要 audit ad-hoc 去翻同 timestamp 的 `_meta.json`。

### D7 — Fail-closed at node boundary,no auto mid-flight fallback

CLI mode 任一 node 失敗(quota exhausted / timeout / parse / tool):
1. LangGraph checkpoint 自動存當前 node 之前的 state
2. 顯示明確錯誤: `node bull_researcher failed: claude-code quota exhausted at 14:32`
3. 使用者下指令: `tradingagents analyze --resume --executor api`(或換 `--executor codex` 試另一個 CLI)
4. 從 checkpoint 接著跑,該 node 用新 executor 重做

**Rationale**: Codex agreed。混 mode 會掩蓋 quota 問題、replay 風格不一致。Codex MVP 立場跟使用者選的 fail-closed 一致。

**未來考慮**: 加 `--allow-fallback` flag 給 dev / demo 場景開自動降級,**first slice 不做**(避免增加分支)。

### D8 — `/trade` slash command 是 thin wrapper

`.claude/commands/trade.md` 內容只 prompt Claude Code session 執行 `tradingagents analyze --executor claude-code <args>`,**不複製** orchestration。LangGraph 仍是 single source of orchestration truth。

**Rationale**: Codex 強調 `/trade` 不能有 duplicate orchestration;duplicate 會引起兩條路徑 drift,後期 maintenance 災難。Slash command 只是 entry-point alias。

### D10 — Decisions MCP tools 對齊既有 schemas.py 真實欄位(implementation 期間 refinement)

**起源**: Phase 2 task 2.3 開工 grep 既有 Pydantic schema,發現 `tradingagents/agents/schemas.py` 早就定義好 `ResearchPlan` / `TraderProposal` / `PortfolioDecision` 三個 schema,各自欄位跟 brainstorm 期間寫的占位名稱(qty/entry/exit/stop_loss / allocation / scale-value)**不同**。

**處理**:
- Decisions MCP tools 參數**直接 import** 既有 schemas.py 並用 Pydantic 自動生成 MCP tool schema,**不重新定義**
- 對應 schema 的真實欄位列在 §D3 表
- 修 spec: `specs/decisions-mcp/spec.md` 同步把參數欄位改成真實名稱
- 修 design `## Goals` 段不需改(原本就承諾「沿用既有 Pydantic schema」)

**Rationale**: 避免 spec / impl / schema 三邊 drift。Pydantic 已是 single source of truth,MCP tool 是 thin wrapper。

### D9 — `NodeSpec._callable` dual-purpose container(implementation 期間 refinement)

**起源**: Phase 1 task 1.5 開工讀 `tradingagents/graph/setup.py` 發現現有結構是 `create_*(llm) → callable(state) → state_delta` — agents 函式本身就是 LangGraph 直接接受的 node 形狀。原 design §3.2 寫「`run_node` 就是 `agents/*/` 各 node 程式碼**搬一搬**」與 §2 "tradingagents/agents/ 不動" 衝突。Implementation 期間發現直接 duplicate 邏輯是錯的(drift risk),改為 **option B**: agents 函式當不透明 callable,透過 NodeSpec 傳給 executor。

**Schema**:

```python
@dataclass
class NodeSpec:
    agent_role: str                              # "market_analyst", "bull_researcher", ...
    prompt_template: str = ""                    # CLI mode 用;API mode 留空
    tools: list[str] = field(default_factory=list)
    schema: Optional[type] = None                # Pydantic schema(Trader/PM)
    retry_policy: dict = field(default_factory=dict)
    _callable: Optional[Callable[[dict], dict]] = None  # API mode 走這條
```

**API mode 路徑**: `executor.run_node(node_name, state, spec)` → `APIExecutor` 看 `spec._callable` 不為 None,直接呼 `spec._callable(state)` 拿回 `state_delta` dict。零 agents 修改、零行為變動。

**CLI mode 路徑**: `executor.run_node(node_name, state, spec)` → `ClaudeCodeExecutor` / `CodexExecutor` / `GeminiExecutor` 看 `spec.agent_role + prompt_template + tools + schema` 構建 subprocess prompt;**忽略** `_callable`(該欄位是 API mode 內部 shim,CLI mode 不應依賴)。

**setup.py refactor**: 每個 `create_*(llm)` 回的 callable 改成包一層 — 把它寫成 NodeSpec(`_callable=`)後丟給 `executor.run_node(...)` 並回 `result.state_delta`。LangGraph add_node 加的是這個 wrapped callable。

**Rationale**:
- 滿足 design §2「`agents/**` 全部不動」承諾
- API mode 行為跟 master 完全相容(包一層 indirection,測試 byte-equivalent baseline)
- CLI mode 不依賴 `_callable`,避免「API/CLI 路徑同個 spec field 各自解讀」的 spec 漏抽象
- `_` 前綴標記為 implementation detail,避免外部依賴

**Spec impact**:
- `specs/api-executor/spec.md` 新增 requirement 描述 `NodeSpec._callable` 角色 + scenario
- `specs/cli-executor/spec.md` 已 covered(CLI executor 只取 `agent_role / prompt_template / tools / schema` 構 subprocess),但補一條明確 scenario 說明「ignore _callable」
- 兩條 spec 之後在 phase 1 task 1.5/1.6 後同 PR commit

## Risks / Trade-offs

### R1 (D2 衍生): Per-agent subprocess 啟動延遲 → Mitigation
- 30-50 個 subprocess × 1-2s = 30-100s 純啟動
- 接受 CLI mode 比 API mode 慢 5-10x
- **Mitigation**: implementation 結尾跑 wallclock benchmark 並寫入 acceptance criterion 9;若實測 > 10x 或 > 5 分鐘,implementation 階段考慮 D2 v2 (session pool reuse 同 model 的 CLI session)。**First slice 不做** session pool — context drift / state leak 風險不在初版 budget。

### R2 (D6 衍生): canonical memory_log 無 executor provenance → Mitigation
- 純翻 `~/.tradingagents/memory/trading_memory.md` 看不出某條 decision 是哪個 mode 產
- **Mitigation**: per-run `_meta.json` 補完整 provenance,timestamp 一致可 join。Audit 流程必須教育成「先翻 memory_log → 拿 timestamp → 開 `./reports/{TICKER}_{TIMESTAMP}/_meta.json`」。

### R3 (D4 衍生): MCP server 暴露的檔案/網路面比 API mode 大 → Mitigation
- API mode 下 yfinance / alpha_vantage Python function 跑在 parent process,有完整 sandbox;CLI mode 下 CLI subprocess 透過 MCP 呼工具,有獨立 process boundary 但少了 in-process control
- **Mitigation**: dataflows MCP server 用 read-only 風格 — 不暴露任何寫盤操作。decisions MCP 只接受 schema-valid submissions,server 端 strict validate。

### R4: Subscription CLI 內部 throttle / quota 行為各家不同 → Mitigation
- Claude Code、Codex、Gemini 各自有自己的 rate limit / daily quota,fail-closed 觸發頻率因 CLI 而異
- **Mitigation**: 各 executor 內部偵測 quota / rate limit pattern → 統一回 `ExecutorError(reason="quota_exhausted")`。Acceptance criterion 9 要求測一次 quota-near-exhausted 場景。

### R5: Windows + 繁中 locale subprocess 編碼地雷 → Mitigation
- 子 CLI 可能是 Node/Rust/Go 不吃 Python locale 設定;PowerShell / cmd 預設 cp950;JSON 含中文走 stdout 容易壞
- **Mitigation**: 完整 env override
  ```python
  env = {**os.environ,
         "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
         "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
         "NO_COLOR": "1", "TERM": "dumb"}
  ```
  stdout decode 用 `errors="replace"`;**永遠不從 human stdout 解析權威輸出**,結構化結果走 MCP tool payload 或 transcript file。Acceptance criterion 9 要求 Windows + 繁中 locale 通過。

### R6: CLI subagent / tool 自主性破壞 trading 可重現性 → Mitigation
- CLI session 自己決定動哪些 tool / 開哪些 subagent,同樣的 prompt 兩次跑可能走不同路徑
- **Mitigation**: 每個 node 的原始 transcript 落地到 `./reports/.../transcripts/{node_name}.{ext}`;`_meta.json` 記 CLI version + model + seed(若 CLI 支援)。**接受**: 訂閱制 CLI 的 trading run 重現性本質上比 API mode 弱,這是訂閱制 + autonomy 兩個 goal 的內生代價。

### R7: 巢狀 Claude Code session 配額 → Open(見 §Open Questions Q1)

### R8: dataflows MCP server 多寫一條啟動路徑 → Mitigation
- API mode 既有 ToolNode 直接呼 Python function,效能最好;CLI mode 走 MCP 多一跳
- **Mitigation**: API mode 初版**兩條都接**(直接 Python function call + MCP client 都可),先觀察 MCP latency overhead;若可忽略,後續 cleanup 統一走 MCP;若太重,API mode 保留直接 call 路徑。

## Migration Plan

採用 5-phase 切法,每個 phase 獨立可 review / merge / verify。同一 OpenSpec change,**不**分多個 PR(避免 review fatigue),但 phase-gated:

**Phase 1 — Executor abstraction**(無 CLI executor,只動 API path)
- `executors/base.py`(NodeExecutor protocol、types)
- `executors/api.py`(包現有 langchain,行為與 master 完全相容)
- `graph/setup.py` 每個 node factory 多吃 executor 參數,**default = api executor**
- `cli/utils.py` 兩段式選單(Step 1 加 mode 選擇,但只露 API 選項;CLI 選項先 stub 顯示「coming soon」)
- **Phase 1 verify gate**: 既有 108 tests + 42 subtests 全綠;`tradingagents analyze SPY 2024-05-10` 跑出來的 final_state 跟 phase 0 baseline diff = 0

**Phase 2 — Decisions MCP server**(獨立可單獨啟動)
- `decisions/mcp_server.py`,暴露 3 個 submit tools
- 內部 import `agents/utils/schemas.py` 既有 Pydantic schema
- **Phase 2 verify gate**: 手動 `python -m mcp_client decisions submit_trader_proposal {...}` 通過 schema validation;`{"qty": "not-a-number"}` 被 reject

**Phase 3 — Dataflows MCP server**(同上獨立)
- `dataflows/mcp_server.py`,包現有 routing
- API mode 改成可選走 MCP client(預設仍走直接 Python function,環境變數 `TRADINGAGENTS_DATAFLOWS_VIA_MCP=1` 切過去)
- **Phase 3 verify gate**: `python -m mcp_client dataflows get_stock_data SPY` 拿到資料;`get_stock_data --vendor alpha_vantage` 切 vendor 也通

**Phase 4 — Claude Code executor**(第一個 CLI executor,跑通端到端)
- `executors/claude_code.py`,spawn `claude --print --output-format json --mcp-config ...`
- 完整 Windows env 設定(R5 mitigation)
- 接 decisions MCP + dataflows MCP
- Quota / timeout / tool failure 統一回 ExecutorError
- `cli/utils.py` Step 1 「Claude Code」選項從 stub 變實作
- **Phase 4 verify gate**: `tradingagents analyze SPY 2024-05-10 --executor claude-code` 跑出來的 final_state 結構跟 API mode 一致(同 keys、rating ∈ {Buy/Overweight/Hold/Underweight/Sell});CLI mode 跑出 memory_log 條目,下次 API run 的 `_resolve_pending_entries` 讀得到;Windows + 繁中 locale 跑不撞 UnicodeDecodeError

**Phase 5 — Codex + Gemini executor + `/trade` slash command**
- `executors/codex.py`、`executors/gemini.py`,沿用 phase 4 abstraction
- `.claude/commands/trade.md` thin wrapper
- `cli/utils.py` Step 1 「Codex」「Gemini」選項從 stub 變實作
- **Phase 5 verify gate**: 三個 CLI executor 各跑通一輪;`/trade SPY 2024-05-10` 在 Claude Code session 內呼叫成功且行為跟 `tradingagents analyze --executor claude-code` 一致

**Rollback strategy**: 每個 phase 完成後 commit 獨立,若 phase N+1 出包,revert 該 phase commit 回到 phase N baseline。Persistence 路徑同檔同格式設計確保兩模式互不污染(API run 留下的 memory_log 不會因 CLI mode 加 fields 而 schema 變動)。

## Open Questions

- **Q1**: Claude Code session 內透過 `/trade` 跑,然後 Phase 4 executor 又 spawn `claude --print ...` child session — **巢狀 Claude Code session 是否被允許 / 是否計同一 quota**? Phase 4 implementation 前需要先寫 smoke test 驗證:在 Claude Code session 跑 `claude --print "hello"` 是否成功、有無 sandbox 阻擋、token usage 是否疊算。若巢狀不行,`/trade` slash command 改為「直接呼叫 API mode 的 tradingagents analyze」當 fallback。
- **Q2**: Gemini CLI 是否原生支援 MCP client? 若無,Gemini executor 結構化輸出走 prompt + JSON + retry(D3 fallback path),不接 decisions MCP。Implementation 階段第一週 verify。
- **Q3**: Claude Code `--print --output-format json` 是否暴露 tool call 細節?若只暴露 final agent_message,decisions MCP 機制等於失效,得退到 prompt + JSON。Implementation 階段第一週 verify。
- **Q4**: `executors/api.py` 包現有 langchain 邏輯時,要不要把 NodeExecutor 抽象推進 `agents/*/` 每個 agent class,還是包在 setup.py 統一處理? Phase 1 implementation 時根據程式碼 shape 決定。傾向後者(setup.py 統一處理,agents/ 不動),維持 agents/ 零修改承諾。
- **Q5**: dataflows MCP server 是否要常駐(systemd / Windows service / launchctl),還是每次 propagate 時 parent process spawn? 初版**每次 spawn**(實作簡單、無常駐基礎設施),Phase 3 implementation 時量測啟動 overhead,若可忽略則維持;若太重(> 2s)考慮常駐或 lazy spawn 持續。
