"""Demo runner that points TradingAgents at NVIDIA NIM (OpenAI-compatible).

NVIDIA NIM exposes hosted DeepSeek/Llama/Nemotron models at
https://integrate.api.nvidia.com/v1 with the same Chat Completions schema
as OpenAI. We reuse the `deepseek` provider branch so DeepSeekChatOpenAI's
thinking-mode round-trip kicks in (deepseek-v4-pro returns reasoning_content
that must be echoed back).
"""
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["backend_url"] = "https://integrate.api.nvidia.com/v1"
config["deep_think_llm"] = "deepseek-ai/deepseek-v4-pro"
config["quick_think_llm"] = "deepseek-ai/deepseek-v4-flash"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2024-05-10")
print("\n========== FINAL DECISION ==========")
print(decision)
