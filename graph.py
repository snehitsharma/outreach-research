
from langgraph.graph import StateGraph, END
from langgraph.types import Send

from config import config
from state import State

from nodes.sanitize import sanitize_node
from nodes.guardrail import guardrail_node
from nodes.planner import planner_node
from nodes.researcher import researcher_node
from nodes.contact_enricher import contact_enrichment_node
from nodes.verifier import verifier_node
from nodes.resolver import resolver_node
from nodes.reranker import reranker_node
from nodes.synthesizer import synthesizer_node
from nodes.outreach_drafter import outreach_drafter_node


def build_graph():
   
    graph = StateGraph(State)

    # Entry node
    graph.add_node("sanitize", sanitize_node)
    graph.set_entry_point("sanitize")
    graph.add_edge("sanitize", "guardrail")

    # Guardrail check
    graph.add_node("guardrail", guardrail_node)

    graph.add_conditional_edges(
    "guardrail",
    lambda state: "planner" if state.guardrail_passed else END,
    ["planner", END],
    )

    # Research planning & fan-out
    graph.add_node("planner", planner_node)

    def fan_out_researchers(state: State) -> list[Send]:
        return [
            Send("researcher", {"angle": angle, "query": state.query, "goal": state.goal, "job_id": state.job_id})
            for angle in state.planner_list or []
        ]

    graph.add_conditional_edges("planner", fan_out_researchers, ["researcher"])

    # Execution & verification loop
    graph.add_node("researcher", researcher_node)
    graph.add_edge("researcher", "verifier")

    graph.add_node("verifier", verifier_node)

    def route_after_verifier(state: State) -> str:
        if state.penalties and state.retry_count < config.MAX_RETRY_ROUNDS:
            return "resolver"
        if state.is_sales_outreach:
            return "contact_enrichment"
        return "reranker"


    graph.add_conditional_edges(
        "verifier",
        route_after_verifier,
        ["resolver", "contact_enrichment",  "reranker"],
    )

    graph.add_node("contact_enrichment", contact_enrichment_node)
    graph.add_edge("contact_enrichment","reranker" )

    # Resolution, ranking & synthesis
    graph.add_node("resolver", resolver_node)
    graph.add_edge("resolver", "verifier")

    graph.add_node("reranker", reranker_node)
    graph.add_edge("reranker", "synthesizer")

    graph.add_node("synthesizer", synthesizer_node)

    # Dynamic route: General Research ends at Synthesizer; Sales Outreach proceeds to Outreach Drafter
    def route_after_synthesizer(state: State) -> str:
        is_sales = state.get("is_sales_outreach", True) if isinstance(state, dict) else getattr(state, "is_sales_outreach", True)
        return "outreach_drafter" if is_sales else END

    graph.add_conditional_edges("synthesizer", route_after_synthesizer, ["outreach_drafter", END])

    # Outreach draft & HITL review state
    graph.add_node("outreach_drafter", outreach_drafter_node)

    def route_after_outreach(state: State) -> str:
        drafts = getattr(state, "drafts", {}) or {}
        return "hitl_wait" if drafts.get("outreach") else END

    graph.add_conditional_edges("outreach_drafter", route_after_outreach, ["hitl_wait", END])

    graph.add_node("hitl_wait", lambda state: state)
    graph.add_conditional_edges("hitl_wait", lambda state: END, [END])

    return graph.compile()
