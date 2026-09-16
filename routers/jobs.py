import os
import uuid
import asyncio
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from dependencies import get_graph
from gmail_mcp_client import gmail_client
from nodes.hitl import get_human_review_payload, get_pending_review, create_gmail_draft
from schemas import ApprovalRequest, JobRequest, JobResponse
from state import State
from langgraph.types import Command


router = APIRouter()
job_states: dict[str, State] = {}
job_statuses: dict[str, str] = {}


def _resolve_status(state: State) -> str:
    if not state.guardrail_passed and state.guardrail_reason:
        return "rejected"

    if get_pending_review(state):
        return "awaiting_approval"

    if state.report and not state.drafts.get("outreach"):
        return "complete_no_outreach"

    return "processing"


def _run_job(job_id: str, initial_state: State, graph: Any) -> None:
    job_statuses[job_id] = "running"
    config = {"configurable": {"thread_id": job_id}}
    try:
        raw_result = graph.invoke(initial_state, config=config)
        raw_result.pop("__interrupt__", None)
        result = State.model_validate(raw_result)
        snapshot = graph.get_state(config)
        job_states[job_id] = result
        job_statuses[job_id] = "awaiting_approval" if snapshot.next else _resolve_status(result)
    except Exception:
        job_statuses[job_id] = "failed"


@router.post(
    "/jobs",
    response_model=JobResponse,
    tags=["Swarm Operations"],
    summary="1. Trigger Autonomous Research Job",
)
def trigger_job(
    request: JobRequest,
    background_tasks: BackgroundTasks,
    graph: Any = Depends(get_graph),
):
    job_id = str(uuid.uuid4())  #have to change this to a more secure way of generating job ids
    initial_state = State.initial(
        job_id=job_id,
        raw_query=request.query,
        goal=request.goal,
    )

    job_statuses[job_id] = "pending"
    background_tasks.add_task(_run_job, job_id, initial_state, graph)

    return JobResponse(job_id=job_id, status="pending") 


@router.get(
    "/jobs/{job_id}",
    tags=["Swarm Operations"],
    summary="3. Get Job Results & Executive Report",
)
def get_job_result(job_id: str):
    status = job_statuses.get(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")

    values = job_states.get(job_id)
    if values is None:
        return {"job_id": job_id, "status": status}

    pending_review = get_pending_review(values)

    if not values.guardrail_passed and values.guardrail_reason:
        return {"job_id": job_id, "status": "rejected", "reason": values.guardrail_reason}

    if pending_review:
        return {
            "job_id": job_id,
            "status": "awaiting_approval",
            "review_payload": get_human_review_payload(values),
            "draft": pending_review,
                "report": values.report,
                "all_contacts": values.verified_contacts,
        }

    if values.report and not values.drafts.get("outreach"):
        return {"job_id": job_id, "status": "complete_no_outreach", "report": values.report}

    return {"job_id": job_id, "status": status}

@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    async def event_stream():
        last_status = None
        while True:
            current = job_statuses.get(job_id)
            if current is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            if current != last_status:
                yield f"data: {json.dumps({'job_id': job_id, 'status': current})}\n\n"
                last_status = current
            if current in ("completed", "failed", "rejected", "awaiting_approval", "complete_no_outreach"):
                break
            await asyncio.sleep(1)
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    "/jobs/{job_id}/report/download",
    tags=["Swarm Operations"],
    summary="4. Download Research Report File (.md)",
)
def download_job_report(job_id: str):
    values = job_states.get(job_id)
    if values is None:
        raise HTTPException(status_code=404, detail="Job not found")

    filepath = values.get("report_filepath") if isinstance(values, dict) else getattr(values, "report_filepath", None)
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Report file not found")

    return FileResponse(
        path=filepath,
        media_type="text/markdown",
        filename=f"research_report_{job_id[:8]}.md",
    )


@router.post(
    "/jobs/{job_id}/approve",
    tags=["Outreach & HITL Approval"],
    summary="5. Approve or Discard Email Draft",
)
def approve_outreach(job_id: str, request: ApprovalRequest, graph: Any = Depends(get_graph)):
    if job_statuses.get(job_id) != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Job is not awaiting approval")

    state = job_states.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    pending_review = get_pending_review(state)
    if not pending_review:
        raise HTTPException(status_code=400, detail="No draft awaiting approval for this job")

    # Follow-up drafts are produced by the background scheduler after the graph run
    # for this job_id has already reached END, so there's no graph interrupt left to
    # resume — resolve the decision directly against job_states, same job_id throughout.
    if pending_review["draft_type"] == "follow_up":
        followups = list(state.drafts.get("follow_up", []))
        followups[0] = followups[0].model_copy(update={
            "approved": request.approved,
            **({"to_email": request.to_email} if request.to_email else {}),
        })
        job_states[job_id] = state.model_copy(update={"drafts": {**state.drafts, "follow_up": followups}})
        job_statuses[job_id] = "completed"

        return {
            "job_id": job_id,
            "status": "approved" if request.approved else "discarded",
            "to_email": request.to_email or pending_review.get("to_email"),
        }

    config = {"configurable": {"thread_id": job_id}}
    snapshot = graph.get_state(config)
    if not snapshot or not snapshot.next:
        raise HTTPException(status_code=404, detail="Job not found or not paused")

    raw_result = graph.invoke(
        Command(resume={"approved": request.approved, "to_email": request.to_email}),
        config=config,
    )
    raw_result.pop("__interrupt__", None)
    result = State.model_validate(raw_result)

    job_states[job_id] = result
    job_statuses[job_id] = "completed"

    return {
        "job_id": job_id,
        "status": "approved" if request.approved else "discarded",
        "to_email": request.to_email or pending_review.get("to_email"),
    }