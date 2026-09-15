

from state import State
from llm_clients import light_llm
from pydantic import BaseModel, Field
from config import config


class PlannerOutput(BaseModel):
    angles: list[str] = Field(default_factory=list, description="List of 3-6 distinct research angles")
    is_sales_outreach: bool = Field(
        default=True
    )


def planner_node(state: State) -> dict:
    
    if state.planner_list:
        return {}

    result = light_llm.generate(
        prompt=f"""Given this research request, break it down into
        {config.MIN_ANGLES}-{config.MAX_ANGLES} distinct research angles.

        classify whether this request is:
        - is_sales_outreach = True: if the query aims for outreach, or looks like a sales or any lead generation.
        - is_sales_outreach = False: if it is a standard research/analysis request (e.g. tech architecture, market trends, company overview) with NO email outreach needed.

        Request: "{state.query}"
        Goal context: "{state.goal or 'not specified'}"
        """,
        response_model=PlannerOutput,
    )

    angles = result.angles or [
        f"{state.query} key requirements",
        f"{state.query} background analysis",
        f"{state.query} overview",
    ]
    angles = angles[:config.MAX_ANGLES]

    return {"planner_list": angles, "is_sales_outreach": result.is_sales_outreach}