# TradingAgents/graph/setup.py

from typing import Any, Callable, Dict, Optional
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.executors import APIExecutor, NodeExecutor, NodeSpec

from .conditional_logic import ConditionalLogic


def _wrap_node_through_executor(
    executor: NodeExecutor,
    node_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    agent_role: str,
    cost_tracker: Optional[list] = None,
    model_usage_tracker: Optional[list] = None,
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Wrap a LangGraph-native node fn so it dispatches through `executor.run_node`.

    For `api` executor, this is a one-extra-call indirection that delegates back to
    the original `node_fn` via NodeSpec._callable — zero behaviour change vs master.
    For CLI executors (claude-code / codex / gemini), the wrapped callable still has
    the same `(state) -> dict` LangGraph signature but the CLI executor ignores
    `_callable` and builds a subprocess prompt from agent_role + spec metadata.

    `cost_tracker` is an optional list the caller passes in; every node's
    `executor_metadata.cost_usd` is appended so the CLI surface can sum the
    total at end-of-run. langgraph state has no native cost-accumulation
    reducer, so we use this side channel rather than threading it through
    state.

    See design §D9.
    """
    spec = NodeSpec(agent_role=agent_role, _callable=node_fn)

    def wrapped(state: Dict[str, Any]) -> Dict[str, Any]:
        result = executor.run_node(agent_role, state, spec)
        meta = result.executor_metadata or {}
        if cost_tracker is not None:
            cost = meta.get("cost_usd")
            if cost is not None:
                cost_tracker.append(float(cost))
        if model_usage_tracker is not None:
            usage = meta.get("model_usage")
            if usage:
                model_usage_tracker.append(
                    {
                        "agent_role": agent_role,
                        "session_id": meta.get("session_id"),
                        "duration_ms": meta.get("duration_ms"),
                        "cost_usd": meta.get("cost_usd"),
                        "models": usage,
                    }
                )
        return result.state_delta

    wrapped.__name__ = f"{agent_role}_via_{executor.name}"
    return wrapped


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        executor: Optional[NodeExecutor] = None,
    ):
        """Initialize with required components.

        Args:
            executor: NodeExecutor that dispatches each agent's chat call.
                Defaults to APIExecutor (existing langchain path). Phase 4/5
                add CLI-backed executors (claude-code / codex / gemini).
        """
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.executor = executor if executor is not None else APIExecutor()
        # Per-node cost reported by CLI executors via executor_metadata.cost_usd.
        # Appended by _wrap_node_through_executor; CLI surface sums at end of
        # run for the "total cost" line. API executor never sets cost_usd so
        # this stays empty in API mode.
        self.cost_tracker: list[float] = []
        # Per-node modelUsage breakdown emitted by ClaudeCodeExecutor; lets the
        # CLI / HTML render show which model (Opus 4.7 vs Haiku 4.5) did how
        # much work across the 22-node pipeline. Empty in API mode.
        self.model_usage_tracker: list[dict] = []

    def setup_graph(
        self, selected_analysts=["market", "social", "news", "fundamentals"]
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Create analyst nodes
        analyst_nodes = {}
        delete_nodes = {}
        tool_nodes = {}

        # All create_*(llm) factories return (state) -> dict callables. We wrap
        # each through `self.executor.run_node` so the executor seam (API vs CLI)
        # works without touching tradingagents/agents/**. See design §D9.
        def _wrap(node_fn, agent_role):
            return _wrap_node_through_executor(
                self.executor,
                node_fn,
                agent_role,
                cost_tracker=self.cost_tracker,
                model_usage_tracker=self.model_usage_tracker,
            )

        if "market" in selected_analysts:
            analyst_nodes["market"] = _wrap(
                create_market_analyst(self.quick_thinking_llm), "market_analyst"
            )
            delete_nodes["market"] = create_msg_delete()
            tool_nodes["market"] = self.tool_nodes["market"]

        if "social" in selected_analysts:
            analyst_nodes["social"] = _wrap(
                create_social_media_analyst(self.quick_thinking_llm), "social_media_analyst"
            )
            delete_nodes["social"] = create_msg_delete()
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = _wrap(
                create_news_analyst(self.quick_thinking_llm), "news_analyst"
            )
            delete_nodes["news"] = create_msg_delete()
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = _wrap(
                create_fundamentals_analyst(self.quick_thinking_llm), "fundamentals_analyst"
            )
            delete_nodes["fundamentals"] = create_msg_delete()
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

        # Create researcher and manager nodes
        bull_researcher_node = _wrap(create_bull_researcher(self.quick_thinking_llm), "bull_researcher")
        bear_researcher_node = _wrap(create_bear_researcher(self.quick_thinking_llm), "bear_researcher")
        research_manager_node = _wrap(create_research_manager(self.deep_thinking_llm), "research_manager")
        trader_node = _wrap(create_trader(self.quick_thinking_llm), "trader")

        # Create risk analysis nodes
        aggressive_analyst = _wrap(create_aggressive_debator(self.quick_thinking_llm), "aggressive_analyst")
        neutral_analyst = _wrap(create_neutral_debator(self.quick_thinking_llm), "neutral_analyst")
        conservative_analyst = _wrap(create_conservative_debator(self.quick_thinking_llm), "conservative_analyst")
        portfolio_manager_node = _wrap(create_portfolio_manager(self.deep_thinking_llm), "portfolio_manager")

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)
            workflow.add_node(
                f"Msg Clear {analyst_type.capitalize()}", delete_nodes[analyst_type]
            )
            workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Define edges
        # Start with the first analyst
        first_analyst = selected_analysts[0]
        workflow.add_edge(START, f"{first_analyst.capitalize()} Analyst")

        # Connect analysts in sequence
        for i, analyst_type in enumerate(selected_analysts):
            current_analyst = f"{analyst_type.capitalize()} Analyst"
            current_tools = f"tools_{analyst_type}"
            current_clear = f"Msg Clear {analyst_type.capitalize()}"

            # Add conditional edges for current analyst
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)

            # Connect to next analyst or to Bull Researcher if this is the last analyst
            if i < len(selected_analysts) - 1:
                next_analyst = f"{selected_analysts[i+1].capitalize()} Analyst"
                workflow.add_edge(current_clear, next_analyst)
            else:
                workflow.add_edge(current_clear, "Bull Researcher")

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
