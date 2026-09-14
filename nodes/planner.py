

from state import State
from llm_clients import cheap_llm
from pydantic import BaseModel, Field
from config import config


class PlannerOutput(BaseModel):
    angles: list[str] = Field(default_factory=list, description="List of 3-6 distinct research angles")
    is_sales_outreach: bool = Field(
        default=True
    )


def planner_node(state: State) -> dict:
    job_id = state.get("job_id") if isinstance(state, dict) else getattr(state, "job_id", None)
    query = state.get("query", "") if isinstance(state, dict) else getattr(state, "query", "")
    goal = state.get("goal") if isinstance(state, dict) else getattr(state, "goal", None)

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

    return {"planner_list": angles, "is_sales_outreach": is_sales}