# Handoff Assessment — TradingAgents

- **專案路徑**：`O:\BZH\Tool\TradingAgents`
- **評估日期**：2026-05-11
- **接手人**：bzh889 (fork: https://github.com/bzh889/TradingAgents)
- **上游**：https://github.com/TauricResearch/TradingAgents (commit `db7e0a6`,版本 v0.2.4)
- **接手目的**：拿來研究/可能改造,需要 ai-global-os 整合,讓未來的 session 認得這個 repo

---

## 1. 專案是什麼(一頁概覽)

**TradingAgents** 是一個用多個 LLM 代理人模擬「真實交易公司運作」的研究框架。一次跑下來會把多個分析師、研究員、交易員、風控、投資組合經理串成一個 LangGraph,對指定股票/日期產出買賣決策。

- **作者群**：Tauric Research (Yijia Xiao 等人,arXiv:2412.20138)
- **License**:看 LICENSE 檔(待補)
- **核心入口**:
  - `main.py` — 直接呼叫 `TradingAgentsGraph().propagate(ticker, date)`
  - `tradingagents` console script (= `cli.main:app`,Typer 介面)
  - `python -m cli.main` — 互動式 CLI

### 主要目錄

| 目錄 | 內容 |
|---|---|
| `tradingagents/` | 套件主體 (3320 行 Python) |
| `tradingagents/agents/` | 分析師(market/news/fundamentals/social)、研究員(bull/bear)、經理(research/portfolio)、交易員、風控 |
| `tradingagents/graph/` | LangGraph 編排:`trading_graph.py`、`checkpointer.py`、`reflection.py`、`signal_processing.py` |
| `tradingagents/llm_clients/` | OpenAI/Google/Anthropic/DeepSeek/Qwen/GLM/Azure/OpenRouter/Ollama 各家 client + `model_catalog.py` |
| `tradingagents/dataflows/` | yfinance/Alpha Vantage 資料抓取 |
| `cli/` | Typer CLI + Rich UI |
| `tests/` | 9 個 pytest 檔 + `conftest.py` |
| `scripts/smoke_structured_output.py` | 多家 provider structured-output 煙霧測試 |

### 跑起來需要的東西

- Python ≥ 3.10 (README 推 3.13;本機是 3.10.10)
- LLM API key (至少一家:OPENAI_API_KEY / GOOGLE_API_KEY / ANTHROPIC_API_KEY / ...)
- 可選:ALPHA_VANTAGE_API_KEY (預設用 yfinance,免 key)
- `uv.lock` 已存在 → 用 `uv sync` 裝相依最快

### 預設執行旗標(`tradingagents` CLI)

```
tradingagents              # 互動式
tradingagents analyze --checkpoint           # 開斷點續跑
tradingagents analyze --clear-checkpoints    # 清掉舊斷點
```

### 持久化路徑(注意:會寫到家目錄)

- 決策日誌:`~/.tradingagents/memory/trading_memory.md` (永遠開啟)
- 斷點 SQLite:`~/.tradingagents/cache/checkpoints/<TICKER>.db`
- 結果輸出:`~/.tradingagents/logs/`
- 三條都有環境變數可覆寫:`TRADINGAGENTS_MEMORY_LOG_PATH` / `TRADINGAGENTS_CACHE_DIR` / `TRADINGAGENTS_RESULTS_DIR`

---

## 2. 關鍵流程 (critical path)

從使用者打 `tradingagents` 一路到產出決策的路徑:

1. `cli/main.py:app` (Typer) → 互動式選 ticker / 日期 / provider / 分析師組合
2. 載入 `.env` (從 CWD 找,不是 site-packages)
3. `TradingAgentsGraph(config)` — `tradingagents/graph/trading_graph.py`
4. 建 LangGraph:分析師 → 研究員(多空辯論)→ 交易員 → 風控 → 投資組合經理
5. `ta.propagate(ticker, date)`:
   - 抓資料:`tradingagents/dataflows/` 走 yfinance / Alpha Vantage
   - 每個 agent 輪流跑 LLM call(走 `tradingagents/llm_clients/<provider>_client.py`)
   - 多空 researchers 辯論 `max_debate_rounds` 次
   - 風控小組辯論 `max_risk_discuss_rounds` 次
   - Portfolio Manager 給最終結構化決策 (Pydantic schema in `agents/schemas.py`)
6. 寫入決策日誌 `~/.tradingagents/memory/trading_memory.md`
7. 下次同 ticker 再跑時,計算上次決策的實現報酬 (raw + alpha vs SPY),把反思灌回 prompt

### 對外接觸面 (contract surface)

- **CLI 旗標**:`--checkpoint`、`--clear-checkpoints`、互動選單
- **Python API**:`TradingAgentsGraph(debug, config).propagate(ticker, date)` → `(state, decision)`
- **Config 鍵**(見 `tradingagents/default_config.py`):
  - LLM:`llm_provider`、`deep_think_llm`、`quick_think_llm`、`backend_url`
  - Thinking 控制:`google_thinking_level` / `openai_reasoning_effort` / `anthropic_effort`
  - 行為:`checkpoint_enabled`、`output_language`、`max_debate_rounds`、`max_risk_discuss_rounds`、`max_recur_limit`
  - 資料源:`data_vendors` (`yfinance` / `alpha_vantage`)
- **環境變數**:`OPENAI_API_KEY` 等十家 + `TRADINGAGENTS_*` 路徑覆寫
- **Docker**:`docker compose run --rm tradingagents` / `--profile ollama`
- **檔案產出**:決策日誌 + checkpoint SQLite + logs 目錄

---

## 3. 熱點(最近兩個月改動最多的檔案)

```
13  cli/main.py
10  pyproject.toml
 9  tradingagents/graph/trading_graph.py
 9  cli/utils.py
 9  README.md
 8  tradingagents/llm_clients/openai_client.py
 8  tradingagents/default_config.py
 7  tradingagents/agents/managers/research_manager.py
 6  tradingagents/llm_clients/model_catalog.py
 6  tradingagents/llm_clients/google_client.py
 6  tradingagents/agents/trader/trader.py
 6  tradingagents/agents/managers/portfolio_manager.py
```

**讀法**:CLI 與 graph 是主要動點,LLM client 與 manager/trader agent 是次要動點。要改任何東西前先 `git log -- <檔名>` 看最近的變動方向。

### 最近 3 個月共 62 commits — 活躍維護中

主要 release 線(從 git log 抓出):
- v0.2.4(`7c37249`):結構化輸出 agents、checkpoint resume、persistent memory log、DeepSeek/Qwen/GLM/Azure
- 安全修補:`2c97bad` ticker 用作路徑前先驗證 (#618)
- 平台修補:`872b063` 全部檔案 I/O 強制 utf-8 (Windows cp1252 crash)
- DeepSeek V4 thinking-mode round-trip(`7e9e7b8`)— 最新

---

## 4. 基準線 (Baseline)

### Build / Install

- 工具:`uv` (uv.lock 存在)、相容 `pip install .`
- 本次接手執行:`uv sync` 完成 (exit 0),`.venv/` 內 239+ 套件
- pytest 不在 runtime deps,另外裝:`uv pip install pytest` → pytest 9.0.3
- Python:3.10.10 (pyproject.toml 要求 ≥3.10)
- **狀態**:✅ 環境就緒

### Tests

- 框架:pytest,`testpaths = ["tests"]`
- markers:`unit` / `integration` / `smoke`
- `tests/conftest.py` 自動填假 API key → unit 測試不用真 key
- 共 9 個測試檔(+ `conftest.py`)、108 收集項

**本次基準線執行**:`.venv/Scripts/python.exe -m pytest -m unit --tb=short`

```
============================= test session starts =============================
platform win32 -- Python 3.10.10, pytest-9.0.3, pluggy-1.6.0
rootdir: O:\BZH\Tool\TradingAgents
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.9.0, langsmith-0.3.45
collected 108 items / 63 deselected / 45 selected

tests\test_deepseek_reasoning.py .........                               [ 20%]
tests\test_google_api_key.py .                                           [ 22%]
tests\test_model_validation.py ...                                       [ 28%]
tests\test_safe_ticker_component.py .......                              [ 44%]
tests\test_signal_processing.py ............                             [ 71%]
tests\test_structured_agents.py ...........                              [ 95%]
tests\test_ticker_symbol_handling.py ..                                  [100%]

========== 45 passed, 63 deselected, 1 warning in 139.74s (0:02:19) ===========
```

- ✅ **45 unit 測試全綠**
- 63 個 deselected:沒掛 `unit` marker 的(checkpoint_resume / memory_log / 部分 ticker_symbol / structured_agents 含 integration 標記)
- 唯一警告:langgraph `allowed_objects` 即將變更預設值 (上游問題,不影響功能)
- 跑完時間 2:19 — Windows + 網路磁碟 I/O 慢,純本機 SSD 應更快

### Lint / type-check

- `pyproject.toml` 沒宣告 ruff / black / mypy → **沒有 lint 與 type-check**(視為發現,不是漏掃)
- 寫進下面風險區。

> **VERIFY 注意事項**:基準線命令的實際輸出在 `uv sync` 與 `pytest` 跑完後會回填到這份 notes,讓未來的 session 可重現。

---

## 5. 風險與未知 (risk register)

| 等級 | 項目 | 說明 |
|---|---|---|
| 高 | 沒 lint / 沒 type-check | `pyproject.toml` 沒宣告 ruff / mypy。任何重構提議都缺結構性安全網 |
| 中 | LLM provider 全部互通有相容性風險 | 9 家 provider client + 1 個 catalog。最近熱點顯示 OpenAI client 與 model_catalog 都頻繁改動,跨家行為差異是常態痛點 |
| 中 | 寫到家目錄 (`~/.tradingagents/`) | 決策日誌、cache、logs 都寫使用者家目錄。Windows 下路徑、編碼、權限都可能踩雷(歷史上 `872b063` 已修過 cp1252 crash) |
| 中 | 互動 CLI 沒有自動化端對端測試 | `cli/main.py` 13 次改動是最高熱點,但 tests/ 沒有 cli/ 對應檔。互動 UX 改動只能靠手動回歸 |
| 中 | yfinance 是預設資料源,但已知會壞 | yfinance 抓 Yahoo HTML,Yahoo 改版過數次。replace 成 alpha_vantage 需要 key,免費額度有限 |
| 中 | 「real money」表面 | 說明寫了「研究用、不是投資建議」,但有 `simulated exchange` 字樣。如果你要 fork 改成真接券商,會踩 finance/合規 雷區 |
| 低 | 只有 LICENSE 沒讀 | LICENSE 檔存在但本評估沒翻內容。fork 後加你自己的程式碼前先確認允許修改的條款 |
| 低 | `requirements.txt` 是 `.` | 就一個點。實際相依靠 `pyproject.toml` 撐。改 `pip install -r requirements.txt` 的人會踩 |
| 低 | `python_requires >= 3.10` 但 README 推 3.13 | 本機 3.10.10 應該能跑,但若用到 3.11+ 才有的功能就會踩 |

---

## 6. 技術債 (debt inventory)

- **`requirements.txt = "."`**:形式上有,實質空殼,容易誤導
- **沒 ruff/black/mypy 設定**:對一個 3000+ 行、9 家 provider 的 codebase 來說是顯著缺口
- **`tests/` 沒分子目錄**:10 個檔平鋪,規模再大會難維護
- **`cli/utils.py` 用 `from cli.utils import *`**:`cli/main.py` 第 31 行,星號 import 是已知踩雷點(難追依賴)
- **路徑常數散在多處**:`default_config.py` + `cli/main.py` 都有 `~/.tradingagents` 邏輯,環境變數覆寫只在 config 裡
- **作者中途切換 memory 系統**:從 BM25 per-agent (`6abc768`) → persistent decision log (`ebd2e12`)。code 留下兩套痕跡的可能性
- **CLI 的 `MessageBuffer` deque 與 Rich Live UI 強耦合**:要替換顯示層難度高

---

## 7. 待澄清(Open Questions — 給未來 session 或 fork 主)

| 問題 | 為什麼重要 |
|---|---|
| **fork 之後我要改什麼?** | 還沒明確。會影響後面要走 `/change-feature` 哪一條 |
| **要對齊上游嗎?** | 上游每月發 minor。fork 改太多會合併困難。要先決定:跟上游 / 偏 fork / 完全分支 |
| **要不要自己接券商 API?** | 目前是 simulated。接 Interactive Brokers / Alpaca / 富邦 e01 是大改,合規影響範圍大 |
| **要不要支援台股?** | yfinance 對台股 ticker(`2330.TW`)支援有限。news 與 fundamentals 來源都偏美股 |
| **要不要加 lint / type-check?** | 沒有結構安全網,改任何東西都需 pytest 全跑。fork 之後加 ruff + mypy 是 cheap win |
| **memory log 隱私?** | `~/.tradingagents/memory/trading_memory.md` 會累積所有決策,跨 session 共用。要不要加密 / 隔離 / per-project? |

---

## 8. ai-global-os 整合狀態

- ✅ Fork 完成 (`https://github.com/bzh889/TradingAgents`)
- ✅ Local remote:`origin` → fork、`upstream` → TauricResearch
- ✅ Branch `main` 追蹤 `origin/main`
- ✅ 寫入 stamp:`.ai-global-os-version` = `d1945ece8b08b368f2d3e5050ddc34c3f6908471`
- ✅ 加進 registry:`~/.claude/ai-global-os-projects.txt`
- ✅ `.gitignore` 已加 `.ai-global-os-version`
- ⏳ **未部署 `.claude/`、skills、`AI-WORKFLOWS.md` 等 OS 入口**:需要重開 session 跑 `init.sh` 觸發 migration prompt

### 下次 session 動作

1. 在 `~/ai-global-os` 跑 `git pull && bash ./init.sh`
2. 進到 `O:/BZH/Tool/TradingAgents` 開新 session
3. init.sh 會偵測到 stamp 並提示部署 `.claude/CLAUDE.md`、`AGENTS.md` 等
4. 同意後就有完整的 OS 體驗 (lifecycle commands、skills、OpenSpec 結構)

---

## 9. 建議第一步(優先序)

| 順序 | 動作 | 理由 |
|---|---|---|
| 1 | 跑完 baseline:`uv sync` 完 → `pytest -m unit` | 沒跑過測試之前任何改動都瞎飛 |
| 2 | 重開 session 跑 init.sh migration | 把 OS 入口部署完 |
| 3 | 釐清「要改什麼」 | 用 `/brainstorming` 或直接寫成 spec 走 `/new-spec` |
| 4 | 加 ruff + mypy(cheap win) | 走 `/change-feature` 提案 |
| 5 | 跟上游同步策略 | 寫一份 README 段落講你 fork 的差異與合併策略 |

---

## Appendix A — 命令輸出原文

### `git log --oneline -5`

```
db7e0a6 fix(cli): load .env from user's CWD when run as console script
7e9e7b8 feat: DeepSeek V4 thinking-mode round-trip via DeepSeekChatOpenAI subclass
2c97bad fix(security): validate ticker before using as path component (#618)
7c37249 chore: release v0.2.4 — structured agents, checkpoint, memory log, providers
4016fd4 fix: stop leaking OpenAI base_url into non-OpenAI provider clients
```

### `git log --since='3 months ago' --oneline | wc -l`

```
62
```

### `python --version`

```
Python 3.10.10
```

### `uv sync` (尾段)

```
+ tzdata==2025.2
+ urllib3==2.4.0
+ uuid-utils==0.14.0
+ w3lib==2.3.1
+ wcwidth==0.2.13
+ websockets==15.0.1
+ xxhash==3.5.0
+ yarl==1.20.1
+ yfinance==0.2.63
+ zstandard==0.23.0
```

(exit code 0)

### `uv pip install pytest`

```
Resolved 9 packages in 1.05s
Installed 4 packages in 4.38s
 + iniconfig==2.3.0
 + pluggy==1.6.0
 + pytest==9.0.3
 + tomli==2.4.1
```

### `pytest -m unit`

```
collected 108 items / 63 deselected / 45 selected
========== 45 passed, 63 deselected, 1 warning in 139.74s (0:02:19) ===========
```

### Build / Lint

```
(待補:無 lint 設定 — 視為發現)
```
