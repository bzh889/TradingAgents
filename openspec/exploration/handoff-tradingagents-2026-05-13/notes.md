# Handoff Assessment — TradingAgents (Re-arch prep, 2026-05-13)

- **專案路徑**: `O:\BZH\Tool\TradingAgents`
- **評估日期**: 2026-05-13 (前一份: 2026-05-11 同目錄旁邊 `handoff-tradingagents-2026-05-11/notes.md`)
- **接手人**: bzh889 (fork: https://github.com/bzh889/TradingAgents)
- **上游**: TauricResearch/TradingAgents,最後一次 upstream commit `db7e0a6` (v0.2.4, 2026-05-10)
- **接手目的**: 規劃**重大 re-architecture**,先建立完整現況基準
- **下一步**: `/change-feature` migration mode 或 `/opsx:propose` 把重點 finding 變成正式 change

---

## 1. 專案是什麼

**TradingAgents** — 用多個 LLM 代理人模擬交易公司決策流程的研究框架。給定 ticker + 日期,跑一整個 LangGraph,從分析師 → 多空辯論 → 交易員 → 風控辯論 → 投資組合經理,最後輸出 Buy/Overweight/Hold/Underweight/Sell 評等。

- **作者群**: Tauric Research (Yijia Xiao 等;arXiv:2412.20138)
- **版本**: 0.2.4
- **License**: 見 LICENSE
- **語言/runtime**: Python ≥ 3.10
- **規模**: `tradingagents/` 4861 行 + `cli/` 1739 行 + `tests/` 10 個檔
- **入口**:
  - Library: `main.py` → `TradingAgentsGraph(...).propagate(ticker, date)`
  - Console script: `tradingagents = "cli.main:app"` (Typer + Rich UI)

### 主要目錄

| 目錄 | 內容 |
|---|---|
| `tradingagents/agents/` | analysts(market/news/social/fundamentals)、researchers(bull/bear)、managers(research/portfolio)、trader、risk_mgmt(aggressive/neutral/conservative) |
| `tradingagents/graph/` | `trading_graph.py`(主類別)、`setup.py`(StateGraph 組裝)、`checkpointer.py`(per-ticker SQLite)、`reflection.py`、`signal_processing.py`、`propagation.py`(state 初始化) |
| `tradingagents/llm_clients/` | OpenAI / Anthropic / Google / Azure 各 client + `openai_client.py`(吃下 xAI/DeepSeek/Qwen/GLM/OpenRouter/Ollama/NVIDIA NIM)+ `model_catalog.py` + `factory.py` |
| `tradingagents/dataflows/` | `interface.py`(vendor routing)+ yfinance / alpha_vantage 各自實作 |
| `tradingagents/agents/utils/` | `memory.py`(append-only decision log)、`agent_states.py`(TypedDict)、`structured.py`(`bind_structured` + fallback)、`rating.py` |
| `cli/` | `main.py`(Typer app + Rich UI)、`utils.py`(provider selection)、`stats_handler.py`、`announcements.py`、`config.py`、`models.py`、`static/` |
| `tests/` | pytest;`conftest.py`(API-key fixtures)+ 9 test 檔(structured_agents / checkpoint_resume / deepseek_reasoning / google_api_key / memory_log / model_validation / safe_ticker_component / signal_processing / ticker_symbol_handling) |
| `scripts/` | `smoke_structured_output.py`(各家 provider 煙霧測試) |
| `openspec/exploration/` | 本份 handoff(以及昨天那份) |

---

## 2. 執行路徑(critical paths)

### Library entry — `TradingAgentsGraph.propagate(ticker, date)`

1. `_resolve_pending_entries(ticker)` — 把過去同一支 ticker 的 pending memory log entry 補上 outcome + reflection (`reflection.py:31-53`)。
2. 若 `checkpoint_enabled=True`,用 `get_checkpointer(ticker)` 開 per-ticker SQLite (`checkpointer.py:34-43`)。thread_id = `SHA256(ticker.upper() + ":" + date)[:16]`。
3. `_run_graph()` — 視 `debug` 而定:
   - `debug=True` 走 `graph.stream(...)`,每個 chunk 印 `chunk["messages"][-1].pretty_print()` (`trading_graph.py:323`,**Windows cp950 雷區**)
   - `debug=False` 走 `graph.invoke(...)`
4. `store_decision()` 寫 pending entry 進 `~/.tradingagents/memory/trading_memory.md` (`memory.py:31-50`)。
5. 成功就清掉 checkpoint。
6. 回傳 `(final_state, parsed_signal)`。

### Graph 節點順序(`setup.py:29-182`)

selected analysts (4 個任選) → 各 analyst 配 ToolNode → bull_researcher ↔ bear_researcher (跑 `max_debate_rounds` 輪) → research_manager → trader (structured `TraderProposal`) → aggressive/neutral/conservative debator (跑 `max_risk_discuss_rounds` 輪) → portfolio_manager (structured `PortfolioDecision`,五級評等) → END。

### CLI entry — `tradingagents analyze [--checkpoint] [--clear-checkpoints]`

互動式 8 步驟:ticker → date → output language → analyst 勾選 → research_depth → provider → quick model → deep model → provider-specific thinking config。然後 `run_analysis()` (`cli/main.py:931-1200`) 用 Rich live layout 顯示進度,把分析師/研究員/交易/風控/PM 五個區塊的報告分別存到 `./reports/{TICKER}_{TIMESTAMP}/{1..5}_*/`。

---

## 3. 對外契約面(blast radius)

> Re-arch 時要動到下面任何一項都會破壞既有使用方式。完整盤點如下。

### 3.1 CLI

- `tradingagents` (互動式無參數) → 走 `get_user_selections()` 8 步驟
- `tradingagents analyze --checkpoint` → 跑可中斷可續跑
- `tradingagents analyze --clear-checkpoints` → 刪掉所有 ticker checkpoint DB
- 互動式 provider 選單目前列出 **10 個** provider(含 NVIDIA NIM 共用 deepseek 分支)

### 3.2 Public Python API

```python
TradingAgentsGraph(
    selected_analysts=["market", "social", "news", "fundamentals"],
    debug=False,
    config: Dict[str, Any] = None,
    callbacks: Optional[List] = None,
)
.propagate(company_name: str, trade_date: str) -> (final_state_dict, parsed_signal)
.process_signal(final_state["final_trade_decision"])
.graph.stream(state, **args)  # 直接戳 LangGraph 也算契約
```

State dict 對外暴露的 key:`company_of_interest` / `trade_date` / `past_context` / `market_report` / `sentiment_report` / `news_report` / `fundamentals_report` / `investment_debate_state` / `trader_investment_plan` / `risk_debate_state` / `final_trade_decision` / `investment_plan`。

### 3.3 Config keys(`tradingagents/default_config.py`)

| Key | 說明 | Env 覆寫 |
|---|---|---|
| `project_dir` | 套件路徑 | — |
| `results_dir` | 輸出 log 目錄 | `TRADINGAGENTS_RESULTS_DIR` |
| `data_cache_dir` | 資料快取 + checkpoint 路徑 | `TRADINGAGENTS_CACHE_DIR` |
| `memory_log_path` | decision log 檔 | `TRADINGAGENTS_MEMORY_LOG_PATH` |
| `memory_log_max_entries` | 翻轉上限(None=不限) | — |
| `llm_provider` | openai/anthropic/google/xai/deepseek/qwen/glm/openrouter/ollama/azure | — |
| `deep_think_llm` / `quick_think_llm` | 兩種思考層級的 model id | — |
| `backend_url` | 自訂 API endpoint(NIM 走這條) | — |
| `google_thinking_level` / `openai_reasoning_effort` / `anthropic_effort` | provider-specific 思考力度 | — |
| `checkpoint_enabled` | 開不開 LangGraph checkpoint | — |
| `output_language` | 報告語言 | — |
| `max_debate_rounds` / `max_risk_discuss_rounds` | 1–5 輪 | — |
| `max_recur_limit` | LangGraph recursion 上限 | — |
| `data_vendors` | 四類 → vendor map | — |
| `tool_vendors` | tool-level vendor 覆寫 | — |

### 3.4 環境變數(共 16)

| Var | 模組 / 用途 |
|---|---|
| `TRADINGAGENTS_RESULTS_DIR` / `TRADINGAGENTS_CACHE_DIR` / `TRADINGAGENTS_MEMORY_LOG_PATH` | `default_config.py:7-9` 路徑覆寫 |
| `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` | 三大 provider |
| `XAI_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `ZHIPU_API_KEY` / `OPENROUTER_API_KEY` | 各家 OpenAI 相容 provider |
| `ALPHA_VANTAGE_API_KEY` | 資料分類覆寫 |
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_DEPLOYMENT_NAME` / `OPENAI_API_VERSION` | Azure |

> CLI 起頭呼叫 `load_dotenv(find_dotenv(usecwd=True))` 讀 `.env`,也讀 `.env.enterprise`。`db7e0a6` 上週才修好 console script 從 site-packages 讀 .env 的 bug。

### 3.5 持久化路徑

| 路徑 | 內容 |
|---|---|
| `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/` | 每次 propagate 的 state dict JSON dump |
| `~/.tradingagents/cache/` | yfinance / Alpha Vantage 回應快取 |
| `~/.tradingagents/cache/{ticker}/checkpoints/{TICKER}.db` | per-ticker SQLite checkpointer |
| `~/.tradingagents/memory/trading_memory.md` | append-only decision log(Phase A pending → Phase B resolved) |
| `./reports/{TICKER}_{TIMESTAMP}/` | CLI 後存的人讀報告 |

### 3.6 LLM providers(10)

| Provider | 模組 | Env | 怪癖 |
|---|---|---|---|
| OpenAI | `openai_client.py` | `OPENAI_API_KEY` | 用 Responses API (/v1/responses) 統一 GPT-4.1/GPT-5 系列 reasoning_effort + tools |
| Anthropic | `anthropic_client.py` | `ANTHROPIC_API_KEY` | extended thinking effort high/medium/low |
| Google | `google_client.py` | `GOOGLE_API_KEY` | Gemini 3.x/2.5,thinking_level 映射 thinking_budget |
| xAI | `openai_client.py` | `XAI_API_KEY` | base_url `api.x.ai/v1` |
| DeepSeek | `openai_client.py` (`DeepSeekChatOpenAI` 子類) | `DEEPSEEK_API_KEY` | thinking-mode 必須 round-trip `reasoning_content`;`deepseek-reasoner` 不支援 tool_choice;`#599` 才剛修 |
| Qwen | `openai_client.py` | `DASHSCOPE_API_KEY` | DashScope `compatible-mode/v1` |
| GLM | `openai_client.py` | `ZHIPU_API_KEY` | `api.z.ai/api/paas/v4/` |
| OpenRouter | `openai_client.py` | `OPENROUTER_API_KEY` | 動態抓 model list,CLI 提示自訂 model id |
| Ollama | `openai_client.py` | — | local `localhost:11434/v1` |
| Azure | `azure_client.py` | 三件套 | deployment-specific |

**特殊**: NVIDIA NIM 不是獨立 provider,在 CLI 端被映射成 `provider_key="deepseek"` + `backend_url="https://integrate.api.nvidia.com/v1"` (`cli/utils.py:252`);又因為 NIM model id 是 `deepseek-ai/deepseek-v4-pro` 這種 namespaced 格式,CLI 在偵測到 `nvidia.com` 時會給 hint 提示用全名 (`cli/utils.py:221-222`)。

### 3.7 資料 vendor(四類 × 兩家,預設 yfinance,fallback 機制)

| 類別 | 工具 | vendor | 預設 |
|---|---|---|---|
| `core_stock_apis` | `get_stock_data` | yfinance / alpha_vantage | yfinance |
| `technical_indicators` | `get_indicators` | yfinance / alpha_vantage | yfinance |
| `fundamental_data` | `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` | 同上 | yfinance |
| `news_data` | `get_news` / `get_global_news` / `get_insider_transactions` | 同上 | yfinance |

`tradingagents/dataflows/interface.py` 在 yfinance 撞到 `AlphaVantageRateLimitError` 時會自動切到 alpha_vantage。

---

## 4. Baseline(可重現的現況)

### 4.1 Test suite

```
$ PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q --no-header
.....................................................................[ 63%]
.................................                                     [ 94%]
......                                                                 [100%]
============================== warnings summary ===============================
.venv/lib/site-packages/langgraph/checkpoint/serde/encrypted.py:5
  LangChainPendingDeprecationWarning: The default value of `allowed_objects`
  will change in a future version. Pass an explicit value (e.g.,
  allowed_objects='messages' or allowed_objects='core') to suppress this warning.
108 passed, 1 warning, 42 subtests passed in 23.26s
```

**baseline 全綠**(108 tests + 42 subtests 全過,23.26s)。**唯一 warning 來自 langgraph 第三方套件**,不是本 repo 程式碼。

### 4.2 Build / import sanity

```
$ .venv/Scripts/python.exe -c "import tradingagents; import cli.main; print('import OK')"
import OK

$ .venv/Scripts/python.exe -c "from tradingagents.graph.trading_graph import TradingAgentsGraph; print('TradingAgentsGraph import OK')"
TradingAgentsGraph import OK
```

(`.venv` 是 uv 建好的,`uv.lock` 已存在;新環境用 `uv sync` 重建一遍 ~30s。)

### 4.3 Lint / formatter / type checker

**沒設**。`pyproject.toml` 沒有任何 `[tool.ruff]` / `[tool.black]` / `[tool.mypy]` / `[tool.pyright]` 區塊;repo 沒有 `.pre-commit-config.yaml` / `ruff.toml` / `mypy.ini` / `.flake8`。

→ 這項本身就是個 finding,寫進下面 5.2。

### 4.4 Source markers

`grep -rn "TODO\|FIXME\|XXX\|HACK" --include="*.py" tradingagents/ cli/` 在 source 內**沒有 hit**(乾淨)。

---

## 5. 風險與未知(risk-and-unknowns register)

> 排序依照 re-arch 規劃時的影響大小。

### 5.1 已知 unresolved bug — Windows cp950 UnicodeEncodeError

- **位置**: `tradingagents/graph/trading_graph.py:323` (`_run_graph` 內 debug 流)
  ```python
  for chunk in self.graph.stream(init_agent_state, **args):
      if len(chunk["messages"]) == 0:
          pass
      else:
          chunk["messages"][-1].pretty_print()   # <-- 這行
          trace.append(chunk)
  ```
- **症狀**: Windows 中文系統(cp950 / cp1252)上,當 message 含 non-ASCII (例如 U+26A0 ⚠) 直接崩。
- **觸發條件**: `debug=True`。`run_demo.py` 就是 `debug=True`,所以你昨天第一次 end-to-end 跑就撞到。
- **workaround**: 環境變數 `PYTHONUTF8=1` (用 `chcp 65001` 也行)。
- **正解**: 把 `pretty_print()` 換成自己控制 encoding 的 print,或 `sys.stdout.reconfigure(encoding="utf-8")` 在 CLI 入口設掉。和 `872b063` 那次「all file I/O 顯式 utf-8」是同類問題,只是漏了 stream 印 chunk 的這條路徑。

### 5.2 沒設 linter / formatter / type checker

- 沒 ruff / black / mypy / pyright / pre-commit hook。靠 author + reviewer 約束。
- **影響**: 4861 + 1739 行 Python,style 漂移時沒有自動把關;re-arch 後想加 type hint 大改也沒得 mypy 守底。
- **建議**: re-arch 第一步 propose 加 ruff (format + lint) + 一條最寬鬆的 mypy 設,讓 baseline 從現在開始凍住風格。

### 5.3 LLM provider 集中在 `openai_client.py` 的單檔(179 行)

- xAI / DeepSeek / Qwen / GLM / OpenRouter / Ollama 都靠 OpenAI-compatible 路徑塞進同一檔。已經是巨型 if-else 分支。NVIDIA NIM 又被掛在 deepseek 分支(共用 `provider_key`)。
- **脆弱點**:
  - NIM 任何時候改 protocol,DeepSeek 也跟著炸(或反過來)
  - 任何 provider 改 base_url 行為,影響面廣(`4016fd4` 就是修「base_url leak 到非 OpenAI client」)
  - 新增 provider 都要在這檔加分支,測試覆蓋率難維持
- **這是 re-arch 最值得處理的單一痛點**(commit 數最多也說明這:openai_client.py 3 個月 8 commits、model_catalog.py 6、google_client.py 6、factory.py 3)。

### 5.4 NIM piggyback on DeepSeek branch

- `cli/utils.py:252` 的 `("NVIDIA NIM (DeepSeek-V4 free tier)", "deepseek", "https://integrate.api.nvidia.com/v1")`
- 等於告訴使用者「把 NIM 的 `nvapi-*` key 放進 `DEEPSEEK_API_KEY`」 (`cli/utils.py:249`)。語意上是 hack。
- 兩個風險:(a) NIM 出了 DeepSeek 以外的模型,使用者期望也能在 menu 直接選;(b) 若 NIM 改 endpoint 或 auth 行為,DeepSeek 一起壞。
- 同檔還有專為 NIM 寫的 model id hint (`cli/utils.py:221-222`),因為 NIM model id 是 `deepseek-ai/deepseek-v4-pro` 這種帶 namespace 的格式,短名會 404。
- → 提示 provider abstraction 設計時,NIM 應該獨立成 `nvidia_nim` provider,不要寄生。

### 5.5 持久化路徑「魔法寫到家目錄」

- `~/.tradingagents/` 下有 logs/cache/memory/checkpoints 四種東西(`default_config.py`)。
- 對使用者不夠透明:首次跑就會無聲生成幾百 MB 快取;memory log 影響到「下一次同 ticker run 的 PM prompt」(因為 `get_past_context()` 把 past decisions 注入 portfolio_manager);user 不一定知道。
- 是否要保留 `~/.tradingagents/` 為預設、還是搬到 `./.tradingagents/`(per-project 隔離),是 re-arch 的政治決定。

### 5.6 結構化輸出仰賴 schema 與 fallback

- `agents/utils/structured.py` 的 `bind_structured(llm, schema, name)` 在 provider 不支援時 fallback 到 freetext。意思是同一個 PM 節點,跑 OpenAI 收到的是 `PortfolioDecision` Pydantic、跑 Ollama 收到的可能是 markdown 字串、`rating.py` 再 heuristic 解 `**Rating**: X`。
- → re-arch 要決定:整個 graph 是否假設 structured output(若否,heuristic 解 rating 就會一直存在邊角錯誤)。

### 5.7 langgraph deprecation warning

- `langchain/langgraph/checkpoint/serde/encrypted.py:5` 已通知 `allowed_objects` 預設值未來會變,要求顯式傳。
- 目前是 PendingDeprecationWarning,不是 error,但未來升級會炸。要在使用 SqliteSaver 的點(`checkpointer.py`)顯式設 `allowed_objects`。

### 5.8 BM25 → decision log 遷移留下的「Phase A / Phase B」雙階段邏輯

- `agents/utils/memory.py` 用「先寫 pending → 等下次同 ticker run 用 outcome resolve」這個兩階段協定。
- 已 ship,但邏輯比 BM25 那版複雜:`_resolve_pending_entries()` 跨 propagate 才結算,失敗(例如使用者中途 Ctrl-C)時的 idempotency 不明顯,需驗證。

### 5.9 reports 的雙寫

- CLI 自己寫一份報告到 `./reports/{TICKER}_{TIMESTAMP}/` 五個子資料夾;同時 `trading_graph._log_state()` 又寫 JSON state 到 `~/.tradingagents/logs/`。
- 兩條落地路徑要在 re-arch 時整合,否則「報告在哪」會持續困擾使用者。

---

## 6. 技術債清單(technical-debt inventory)

| # | 項目 | 位置 | 一句話 |
|---|---|---|---|
| D1 | 無 formatter / linter / type checker | repo root | re-arch 前先設,擋未來漂移 |
| D2 | `openai_client.py` 10-provider monolith | `tradingagents/llm_clients/openai_client.py` | 拆成 per-provider class + 共享 base |
| D3 | NIM 寄生 DeepSeek 分支 | `cli/utils.py:221-222,246-252` | NIM 該升格獨立 provider key |
| D4 | `pretty_print()` 沒有處理 stdout encoding | `tradingagents/graph/trading_graph.py:323` | utf-8 reconfigure stdout 或自寫 printer |
| D5 | rating 用 heuristic regex 解 markdown | `agents/utils/rating.py` | 結構化輸出全面化後可移除 |
| D6 | `~/.tradingagents/` 四種角色(logs/cache/memory/checkpoints) 混在同個 root | `default_config.py:7-9` | 分區或允許 per-project override |
| D7 | report 雙寫 (`./reports/` + `~/.tradingagents/logs/`) | `cli/main.py:931-1200`, `trading_graph.py:_log_state` | 統一輸出路徑 |
| D8 | LangGraph `allowed_objects` 未顯式傳 | `tradingagents/graph/checkpointer.py` | 升 langgraph 前先補 |
| D9 | provider 怪癖散在 `openai_client.py` 與 `cli/utils.py` | 多處 | 集中到 provider class 自己揭露 capabilities |
| D10 | `_resolve_pending_entries` 中斷恢復路徑沒有測試 | `tradingagents/graph/trading_graph.py:229-263` | 加 idempotency 測試 |

---

## 7. Open questions(re-arch 決策前要釐清)

| Q | 主題 | 問題 |
|---|---|---|
| Q1 | **Provider abstraction 邊界** | 拆 `openai_client.py` 時,共享什麼?各家不同的 thinking 參數、structured output 限制、tool_choice 支援度,要不要每個 provider 自己宣告 capability matrix,讓 graph 自動 fallback? |
| Q2 | **Graph composability** | LangGraph 目前是 hard-coded 五階段(analysts → debate → trader → risk → PM)。要不要允許使用者組自己的 graph(例如砍掉 risk 階段、加一個 macro-news 階段)?如果要,API 怎麼長? |
| Q3 | **Deployment story** | 目前 Dockerfile 存在但偏簡單。Re-arch 後是 (a) 純研究 CLI、(b) 可部署的 API service、(c) 兩者都支援?選 (c) 會把 persistence 從家目錄改成 explicit storage backend(redis 已在 deps 但未用)。 |
| Q4 | **Persistence layout** | `~/.tradingagents/` 是 user-level 還是 project-level?Memory log 是否要 ticker × user 區隔(避免互污染)?Checkpoint 是否要 TTL? |
| Q5 | **資料 vendor 抽象** | yfinance vs alpha_vantage 已 fallback。要不要支援 self-hosted data(本地 CSV、自家 DB)?Polygon / IEX 之類的第三家 vendor? |
| Q6 | **Structured output 是否強制** | 若強制(只接 schema),Ollama / 部分 small model 會被排除。若不強制,heuristic rating parsing 永遠存在。trade-off 哪邊? |
| Q7 | **CLI 與 Library 的分工** | `cli/main.py` 939 行,大量邏輯(report 切片、status tracking)寫在 CLI 端。Library 端要不要直接吐 chunked progress events,讓 CLI 變薄? |
| Q8 | **重點 LLM 升級節奏** | 上週才修 DeepSeek V4 thinking-mode 跟新增 NVIDIA NIM,3 個月內 LLM 相關 commit 占 ~40%。Re-arch 是否要為「新模型上線」設計 plugin 介面,不要每次都改 core? |

---

## 8. Re-arch 建議優先順序

| Rank | 動作 | 為什麼 |
|---|---|---|
| 1 | 修 D4 (cp950 stdout encoding) | 1 行修法,擋掉 Windows 使用者第一次 end-to-end 跑就炸 |
| 2 | 加 ruff + 最寬鬆 mypy (D1) | 凍住 baseline 風格,後面大改才有得測 |
| 3 | 回答 Q1 (provider abstraction 邊界) | 不釐清就動 D2 / D3 / D9 會白費 |
| 4 | 提案 D2 + D3 + D9 一起做 (LLM provider 重構) | 牽連最多 commit hotspot,做完最有感 |
| 5 | 回答 Q2 (graph composability) | 影響 D6 / D7 / Q3 的設計 |
| 6 | 補 D8 (langgraph allowed_objects) | 防 langgraph 升級炸 |
| 7 | D5 + Q6 (structured output 政策) | 影響 rating heuristic 是否能拆 |
| 8 | D10 (pending entry idempotency 測試) | 為 D6 / Q4 (persistence 重整) 鋪路 |

→ **建議下一步**: 用 `/change-feature` migration mode 把 **Q1 + D2 + D3 + D9** 包成一個正式 change(provider 抽象重構),這是最大產出。D4 那一行 bug 直接走 `/bugfix-incident`,不要塞進大改。

---

## 9. 參考(prior + 來源)

- 前一份 handoff: `openspec/exploration/handoff-tradingagents-2026-05-11/notes.md` (308 行,內容是同一份 repo 的更早視角;本份 supersede 它的 contract surface + baseline 部份)
- 你昨天 + 今天的 commits: `e7b434b` (takeover + NIM demo)、`67bb45d` (NIM provider hint + custom-model)
- 最近 3 個月最常改的檔: `cli/main.py` (14)、`cli/utils.py` (10)、`pyproject.toml` (10)、`trading_graph.py` (9)、`openai_client.py` (8)、`research_manager.py` (7)、`portfolio_manager.py` (7)、`trader.py` (6)、`model_catalog.py` (6)、`google_client.py` (6)
