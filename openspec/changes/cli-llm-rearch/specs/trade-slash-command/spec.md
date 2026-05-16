## ADDED Requirements

### Requirement: `/trade` slash command 為 thin wrapper

`.claude/commands/trade.md` SHALL 為 Claude Code slash command 定義檔,其行為 SHALL 只 prompt Claude Code session 執行 `tradingagents analyze --executor claude-code <args>`。SHALL NOT 在 slash command 中複製 LangGraph orchestration 邏輯。

#### Scenario: /trade 啟動 trading 流程
- **WHEN** 使用者在 Claude Code session 內輸入 `/trade SPY 2024-05-10`
- **THEN** Claude Code session 執行 `tradingagents analyze --executor claude-code SPY 2024-05-10`,行為跟在 terminal 直接跑該指令一致

#### Scenario: /trade 不引入 orchestration drift
- **WHEN** 開發者修改 LangGraph node 順序或 debate 輪次
- **THEN** `/trade` 行為自動跟 `tradingagents analyze` 一致,不需要同步修改 trade.md;一切 orchestration 唯一 source = `tradingagents/graph/`

### Requirement: 預設 executor = `claude-code`

`.claude/commands/trade.md` SHALL 預設使用 `--executor claude-code`(因為 slash command 本身在 Claude Code session 內被叫,訂閱配額已在使用者範圍內最自然)。SHALL 允許使用者透過參數覆寫,例如 `/trade SPY 2024-05-10 --executor api` 或 `/trade --executor codex`。

#### Scenario: 預設委派給 Claude Code executor
- **WHEN** 使用者輸入 `/trade SPY 2024-05-10`(無額外 flag)
- **THEN** 底層執行 `tradingagents analyze --executor claude-code SPY 2024-05-10`

#### Scenario: 使用者覆寫 executor
- **WHEN** 使用者輸入 `/trade SPY 2024-05-10 --executor codex`
- **THEN** 底層執行 `tradingagents analyze --executor codex SPY 2024-05-10`,使用 Codex CLI 完成

### Requirement: 巢狀 Claude Code session 行為記錄

`/trade` 觸發後,parent Claude Code session 跟 child Claude Code session(executor 內 spawn)之間的關係 SHALL 在 trade.md 文件中明確說明(配額計算、sandbox 行為、限制)。若 implementation 階段驗證巢狀不可行,trade.md SHALL 改為強制 `--executor api`,並在文件解釋原因。

#### Scenario: 文件描述巢狀情境
- **WHEN** 讀 `.claude/commands/trade.md`
- **THEN** 文件含一節描述「running /trade inside Claude Code spawns claude --print child」的當前驗證狀態(可用 / 不可用 / 未驗證)
