

from state import State
from llm_clients import cheap_llm
from pydantic import BaseModel, Field
from config import config
from events import events_manager


class PlannerOutput(BaseModel):
    angles: list[str] = Field(default_factory=list, description="List of 3-6 distinct research angles")
    is_sales_outreach: bool = Field(
        default=True
    )


def planner_node(state: State) -> dict:
    job_id = state.get("job_id") if isinstance(state, dict) else getattr(state, "job_id", None)
    query = state.get("query", "") if isinstance(state, dict) else getattr(state, "query", "")
    goal = state.get("goal") if isinstance(state, dict) else getattr(state, "goal", None)

    if job_id:
        events_manager.emit(job_id, "planner", "thinking", f"Planning parallel research angles & classifying intent for query: '{query}'")

    planner_list = state.get("planner_list") if isinstance(state, dict) else getattr(state, "planner_list", [])
    if planner_list:
        return {}

    result = cheap_llm.generate(
        prompt=f"""Given this research request, break it down into
        {config.MIN_ANGLES}-{config.MAX_ANGLES} distinct research angles.

        classify whether this request is:
        - is_sales_outreach = True: if the query aims for outreach, or looks like a sales or any lead generation.
        - is_sales_outreach = False: if it is a standard research/analysis request (e.g. tech architecture, market trends, company overview) with NO email outreach needed.

        Request: "{query}"
        Goal context: "{goal or 'not specified'}"
        """,
        response_model=PlannerOutput,
    )

    angles = getattr(result, "angles", []) or []
    is_sales = getattr(result, "is_sales_outreach", True)

    if not angles:
        angles = [
            f"{query} key requirements",
            f"{query} background analysis",
            f"{query} overview"
        ]

    angles = angles[:config.MAX_ANGLES]

    if job_id:
        events_manager.emit(
            job_id,
            "planner",
            "complete",
            f"Planner classified workflow as {'SALES OUTREACH (Outreach Draft Enabled)' if is_sales else 'GENERAL RESEARCH (Report Only)'} and generated {len(angles)} angles.",
            payload={"angles": angles, "is_sales_outreach": is_sales},
        )

    return {"planner_list": angles, "is_sales_outreach": is_sales}