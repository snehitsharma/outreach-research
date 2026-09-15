from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Annotated
import operator

from schemas import Contact, Finding, Penalty, Report, DraftItem


class SanitizeMeta(BaseModel):
    was_truncated: bool = False
    injection_flagged: bool = False

class State(BaseModel):
    model_config = ConfigDict(extra="allow")
    #input and sanitize
    job_id: str 
    raw_query: str

    #guardrail
    query: str = ""
    goal: str 
    is_sales_outreach: bool = True

    sanitize_meta: dict = {}

    guardrail_passed: bool = False
    guardrail_reason: str | None = None

    retry_count: int = 0
    

    planner_list: list[str] = []
    findings: Annotated[list[Finding], operator.add] = []
    contacts: Annotated[list[Contact], operator.add] = []
    penalties: Annotated[list[Penalty], operator.add] = []
    resolved_penalties: Annotated[list[Penalty], operator.add] = []
    reranked: list[Finding] = []
    report: Report | None = None

    drafts: dict[str, list[DraftItem]] = {
        "outreach": [],
        "follow_up": [],
    }

    hitl_approved: bool | None = None
    follow_up_at: datetime | None = None

    @classmethod
    def initial(cls, job_id: str, raw_query: str, goal: str | None = None) -> dict:
        return cls(
            job_id=job_id,
            raw_query=raw_query,
            goal=goal,
        )
