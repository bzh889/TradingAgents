"""Quick smoke: can we round-trip a single LLM call to NVIDIA NIM?"""
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

from tradingagents.llm_clients.openai_client import OpenAIClient

client = OpenAIClient(
    model="deepseek-ai/deepseek-v4-flash",
    base_url="https://integrate.api.nvidia.com/v1",
    provider="deepseek",
)
llm = client.get_llm()
resp = llm.invoke("Say 'hello from NVIDIA NIM' and nothing else.")
print("RESPONSE:", resp)
