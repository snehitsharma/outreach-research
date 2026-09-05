# ============================================================
# graph.py — LangGraph Pipeline Architecture with Telemetry
# ============================================================

from typing import Any
from langgraph.graph import StateGraph, END
from langgraph.types import Send

from config import config
from state import State

from nodes.sanitize import sanitize_node
from nodes.guardrail import guardrail_node
from nodes.planner import planner_node
from nodes.researcher import researcher_node
from nodes.verifier import verifier_node
from nodes.resolver import resolver_node
from nodes.reranker import reranker_node
from nodes.synthesizer import synthesizer_node
from nodes.outreach_drafter import outreach_drafter_node


def build_graph(checkpointer: Any = None) -> Any:
    """Builds and compiles the Sales Outreach Research Graph."""
    graph = StateGraph(State)

    # Entry node
    graph.add_node("sanitize", sanitize_node)
    graph.set_entry_point("sanitize")
    graph.add_edge("sanitize", "guardrail")

    # Guardrail check
    graph.add_node("guardrail", guardrail_node)

    def route_after_guardrail(state: State) -> str:
        passed = state.get("guardrail_passed", False) if isinstance(state, dict) else getattr(state, "guardrail_passed", False)
        return "planner" if passed else END

    graph.add_conditional_edges("guardrail", route_after_guardrail, ["planner", END])

    # Research planning & fan-out
    graph.add_node("planner", planner_node)

    def fan_out_researchers(state: State) -> list[Send]:
        if isinstance(state, dict):
            planner_list = state.get("planner_list") or []
            query = state.get("query", "")
            goal = state.get("goal")
            job_id = state.get("job_id")
        else:
            planner_list = getattr(state, "planner_list", []) or []
            query = getattr(state, "query", "")
            goal = getattr(state, "goal", None)
            job_id = getattr(state, "job_id", None)

        return [
            Send("researcher", {"angle": angle, "query": query, "goal": goal, "job_id": job_id})
            for angle in planner_list
        ]

    graph.add_conditional_edges("planner", fan_out_researchers, ["researcher"])

    # Execution & verification loop
    graph.add_node("researcher", researcher_node)
    graph.add_edge("researcher", "verifier")

    graph.add_node("verifier", verifier_node)

    def route_after_verifier(state: State) -> str:
        penalties = getattr(state, "penalties", None)
        retry_count = getattr(state, "retry_count", 0)
        if penalties and retry_count < config.MAX_RETRY_ROUNDS:
            return "resolver"
        return "reranker"

    graph.add_conditional_edges("verifier", route_after_verifier, ["resolver", "reranker"])

    # Resolution, ranking & synthesis
    graph.add_node("resolver", resolver_node)
    graph.add_edge("resolver", "reranker")

    graph.add_node("reranker", reranker_node)
    graph.add_edge("reranker", "synthesizer")

    graph.add_node("synthesizer", synthesizer_node)

    # Dynamic route: General Research ends at Synthesizer; Sales Outreach proceeds to Outreach Drafter
    def route_after_synthesizer(state: State) -> str:
        is_sales = state.get("is_sales_outreach", True) if isinstance(state, dict) else getattr(state, "is_sales_outreach", True)
        return "outreach_drafter" if is_sales else END

    graph.add_conditional_edges("synthesizer", route_after_synthesizer, ["outreach_drafter", END])

    # Outreach draft & HITL interrupt
    graph.add_node("outreach_drafter", outreach_drafter_node)

    def route_after_outreach(state: State) -> str:
        drafts = getattr(state, "drafts", {}) or {}
        return "hitl_wait" if drafts.get("outreach") else END

    graph.add_conditional_edges("outreach_drafter", route_after_outreach, ["hitl_wait", END])

    graph.add_node("hitl_wait", lambda state: state)
    graph.add_conditional_edges("hitl_wait", lambda state: END, [END])

    return graph.compile(checkpointer=checkpointer, interrupt_before=["hitl_wait"])
