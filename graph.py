
from datetime import datetime, timedelta, timezone

from langgraph.graph import StateGraph, END
from langgraph.types import Send, interrupt
from langgraph.checkpoint.memory import MemorySaver

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
        return "outreach_drafter" if state.is_sales_outreach else END

    graph.add_conditional_edges("synthesizer", route_after_synthesizer, ["outreach_drafter", END])

    # Outreach draft & HITL review state
    graph.add_node("outreach_drafter", outreach_drafter_node)

    def route_after_outreach(state: State) -> str:
        return "hitl_wait" if state.drafts.get("outreach") else END


    graph.add_conditional_edges("outreach_drafter", route_after_outreach, ["hitl_wait", END])

    def hitl_wait_node(state: State) -> dict:
        decision = interrupt({
            "report_summary": state.report.summary if state.report else None,
            "drafts": {
                "outreach": [d.model_dump() for d in state.drafts.get("outreach", [])],
            },
            "message": "Review the outreach draft and approve or decline.",
        })
        approved = decision.get("approved", False)
        to_email = decision.get("to_email")
        drafts = {kind: list(items) for kind, items in state.drafts.items()}

        if drafts.get("outreach"):
            draft_update = {"approved": approved}
            if to_email:
                draft_update["to_email"] = to_email
            drafts["outreach"][0] = drafts["outreach"][0].model_copy(update=draft_update)

        follow_up_at = (
            datetime.now(timezone.utc) + timedelta(days=config.FOLLOW_UP_DELAY_DAYS)
            if approved
            else None
        )
        return {
            "drafts": drafts,
            "follow_up_at": follow_up_at,
        }

    graph.add_node("hitl_wait",hitl_wait_node )
    graph.add_edge("hitl_wait", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)