## ADDED Requirements

### Requirement: Two-stage interactive selector

The `tradingagents` CLI互動式選單 SHALL 由現有單一階段(LLM provider 選擇)升級為兩段式: Step 1 選 execution mode、Step 2 conditional 選 provider/executor 配置。Step 1 選項 SHALL 包含 `API (langchain)`、`Claude Code (subscription)`、`Codex CLI (subscription)`、`Gemini CLI (subscription)` 四項。

#### Scenario: 使用者選 API mode
- **WHEN** 使用者跑 `tradingagents` 互動,Step 1 選 `API (langchain)`
- **THEN** Step 2 出現現有 10-provider 選單(OpenAI/Anthropic/Google/Azure/xAI/DeepSeek/Qwen/GLM/OpenRouter/Ollama),選完之後 graph 用 `api` executor 跑

#### Scenario: 使用者選 CLI mode
- **WHEN** 使用者跑 `tradingagents` 互動,Step 1 選 `Claude Code (subscription)`
- **THEN** 系統驗證 `which claude` 在 PATH;通過後讓使用者覆寫預設 model(可選)跟 backend_url(可選);graph 用 `claude-code` executor 跑

#### Scenario: 使用者選 CLI mode 但 CLI 不在 PATH
- **WHEN** 使用者選 `Codex CLI` 但本機沒裝 `codex` 命令
- **THEN** 系統顯示明確錯誤訊息(含安裝建議 `npm install -g @openai/codex` 或文件連結),拒絕進入 Step 2,退回 Step 1

### Requirement: `--executor` flag 旁路 互動式選單

`tradingagents analyze` SHALL 接受 `--executor {api|claude-code|codex|gemini}` flag。當提供 flag 時,Step 1 互動式選擇 SHALL 跳過。Step 2(provider/CLI 設定)仍可保留為互動式或由額外 flag 控制。

#### Scenario: CLI flag 跳過 mode 選擇
- **WHEN** 使用者跑 `tradingagents analyze SPY 2024-05-10 --executor claude-code`
- **THEN** 系統直接驗證 `claude` 在 PATH,跳過 Step 1 mode 選單,進到 Step 2 或直接執行

#### Scenario: 無效 executor 值
- **WHEN** 使用者跑 `tradingagents analyze --executor invalid-name`
- **THEN** 系統顯示錯誤訊息列出合法值 `{api, claude-code, codex, gemini}` 並 exit code 非零

### Requirement: 旗標 `--resume --executor` 切換 executor 接續

`tradingagents analyze --resume --executor <name>` SHALL 從 LangGraph checkpoint 接續,且該 propagate 從接續點之後 SHALL 使用 `<name>` 指定的 executor。

#### Scenario: API mode 接 CLI mode 中斷
- **WHEN** 上一次 propagate 在 CLI mode 跑到 node 6 quota_exhausted 卡住,使用者跑 `tradingagents analyze --resume --executor api`
- **THEN** 系統從 node 6 接續,從 node 6 開始所有 node 用 `api` executor;memory_log 跟之前的 CLI run 寫入同一個 entry block(沒新建)
