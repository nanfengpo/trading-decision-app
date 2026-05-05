"""
Parallel analyst execution via LangGraph sub-graph isolation.

Why this exists
---------------
TradingAgents' default graph runs the 4 analysts sequentially, sharing
``AgentState.messages`` as a single working scratchpad. Each analyst's
internal tool-call/result thread plays out on that shared channel before
``msg_clear`` wipes it for the next analyst. End-to-end this is ~3 minutes
per LIVE decision (4 × ~25 s analyst loops + the rest).

Naively running them in parallel by adding ``START → analyst_X`` edges
for each X corrupts that scratchpad — concurrent ``AIMessage(tool_calls)``
+ ``ToolMessage`` writes interleave on ``messages`` and the LLMs lose
track of which result belongs to which call.

The fix in this module: each analyst is wrapped as a **compiled
sub-StateGraph** with its OWN ``messages`` channel. The wrapper at the
parent level reads only inputs the analyst needs (``company_of_interest``
+ ``trade_date``), runs the subgraph in isolation, and returns ONLY the
analyst's report field back to the parent. The parent's ``messages``
channel is never touched.

Net effect: 4 analysts run truly in parallel with no message-channel
contention. Wall-clock per LIVE decision drops from ~3 min to ~1.5 min.

Activation
----------
Set ``cfg["parallel_analysts"] = True`` (or env ``TRADINGAGENTS_PARALLEL_ANALYSTS=1``).
Default is False — sequential mode is unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from langgraph.graph import END, START, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode

logger = logging.getLogger(__name__)


# ---- private state schema ------------------------------------------------

class _AnalystSubState(MessagesState):
    """Private state for one analyst's sub-graph.

    Inherits ``messages`` from MessagesState (with the add_messages
    reducer). Each analyst's tool loop runs on this LOCAL channel —
    isolated from siblings and from the parent.

    All four ``*_report`` fields are present so any analyst's existing
    factory (which assigns to its own field) works without modification.
    Only the relevant field is propagated back to the parent by the
    isolation wrapper.
    """
    company_of_interest: str
    trade_date: str
    market_report: str
    sentiment_report: str
    news_report: str
    fundamentals_report: str
    sender: str


# ---- subgraph builder ---------------------------------------------------

def build_analyst_subgraph(
    analyst_node: Callable,
    tool_node: ToolNode,
    delete_node: Callable,
    condition_fn: Callable,
):
    """Wrap one analyst's loop into a compiled, message-isolated subgraph.

    Mirrors the sequential pattern (analyst → tools | clear) but lives in
    its own state schema so messages don't leak.
    """
    sub = StateGraph(_AnalystSubState)
    sub.add_node("analyst", analyst_node)
    sub.add_node("tools", tool_node)
    sub.add_node("clear", delete_node)

    sub.add_edge(START, "analyst")
    sub.add_conditional_edges("analyst", condition_fn, ["tools", "clear"])
    sub.add_edge("tools", "analyst")
    sub.add_edge("clear", END)

    return sub.compile()


# ---- isolation wrapper ---------------------------------------------------

# Each analyst writes to a different report field
_REPORT_FIELDS = {
    "market":       "market_report",
    "social":       "sentiment_report",
    "news":         "news_report",
    "fundamentals": "fundamentals_report",
}


def make_isolated_node(analyst_type: str, sub_graph) -> Callable:
    """Return a parent-level node that runs a subgraph in isolation.

    The wrapper:
      1. Pulls only ``company_of_interest`` + ``trade_date`` from parent
         state — does NOT pass parent's ``messages`` (so the analyst's
         private message buffer starts fresh).
      2. Invokes the compiled subgraph.
      3. Returns ONLY the relevant report field to the parent.

    This is what prevents 4 concurrent analysts from clobbering each
    other's tool-call/result threads on the parent's ``messages`` channel.
    """
    report_field = _REPORT_FIELDS[analyst_type]

    def _isolated(state: Dict[str, Any]) -> Dict[str, Any]:
        sub_state: Dict[str, Any] = {
            "messages": [("human", state.get("company_of_interest", ""))],
            "company_of_interest": state.get("company_of_interest", ""),
            "trade_date": state.get("trade_date", ""),
        }
        try:
            result = sub_graph.invoke(sub_state)
        except Exception as e:
            logger.exception("isolated %s analyst failed", analyst_type)
            return {report_field: f"_(analyst failed: {e})_"}
        return {report_field: result.get(report_field, "")}

    return _isolated


# ---- top-level wiring ---------------------------------------------------

def wire_parallel_analysts(
    workflow: StateGraph,
    selected_analysts: list,
    analyst_nodes: Dict[str, Callable],
    delete_nodes: Dict[str, Callable],
    tool_nodes: Dict[str, ToolNode],
    conditional_logic,
    join_node_name: str = "Analysts Done",
    next_node_name: str = "Bull Researcher",
) -> None:
    """Add parallel analysts + barrier-join to ``workflow``.

    The caller is responsible for adding all OTHER nodes (researchers,
    risk debators, trader, portfolio manager) and edges from
    ``join_node_name`` onward.

    After this call the workflow has:
      - one node per analyst (each is an isolated subgraph)
      - START → all analysts (parallel fan-out)
      - all analysts → join_node_name (barrier — waits for all)
      - join_node_name → next_node_name
    """
    # Build subgraphs + isolation wrappers
    isolated = {}
    for atype in selected_analysts:
        sub = build_analyst_subgraph(
            analyst_nodes[atype],
            tool_nodes[atype],
            delete_nodes[atype],
            getattr(conditional_logic, f"should_continue_{atype}"),
        )
        isolated[atype] = make_isolated_node(atype, sub)

    # Add to parent workflow
    cap = lambda t: f"{t.capitalize()} Analyst"
    for atype in selected_analysts:
        workflow.add_node(cap(atype), isolated[atype])
        workflow.add_edge(START, cap(atype))

    # Barrier — a no-op join. LangGraph waits for all incoming edges.
    workflow.add_node(join_node_name, lambda s: {})
    for atype in selected_analysts:
        workflow.add_edge(cap(atype), join_node_name)
    workflow.add_edge(join_node_name, next_node_name)
