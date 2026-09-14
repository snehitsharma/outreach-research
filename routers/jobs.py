import os
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse

from dependencies import get_graph
from gmail_mcp_client import gmail_client
from nodes.hitl import get_human_review_payload, get_pending_review
from schemas import ApprovalRequest, JobRequest, JobResponse
from state import State


router = APIRouter()
job_states: dict[str, dict] = {}
job_statuses: dict[str, str] = {}


def _resolve_status(state: Any) -> str:
    values = state if isinstance(state, dict) else getattr(state, "values", None) or state

    if not values.get("guardrail_passed", True) and values.get("guardrail_reason"):
        return "rejected"

    if get_pending_review(values):
        return "awaiting_approval"

    if values.get("report") and not (values.get("drafts") or {}).get("outreach"):
        return "complete_no_outreach"

    return "processing"


def _run_job(job_id: str, initial_state: dict, graph: Any) -> None:
    job_statuses[job_id] = "running"
    try:
        state = graph.invoke(
            initial_state,
            config={
                "run_name": "sales_outreach_job",
                "metadata": {"job_id": job_id},
            },
        )
        job_states[job_id] = state
        resolved_status = _resolve_status(state)
        if resolved_status == "awaiting_approval":
            job_statuses[job_id] = "awaiting_approval"
        elif resolved_status == "rejected":
            job_statuses[job_id] = "rejected"
        else:
            job_statuses[job_id] = "completed"
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

    if not values.get("guardrail_passed", True) and values.get("guardrail_reason"):
        return {"job_id": job_id, "status": "rejected", "reason": values["guardrail_reason"]}

    if pending_review:
        return {
            "job_id": job_id,
            "status": "awaiting_approval",
            "review_payload": get_human_review_payload(values),
            "draft": pending_review,
            "report": values.get("report"),
            "all_contacts": values.get("contacts"),
        }

    if values.get("report") and not (values.get("drafts") or {}).get("outreach"):
        return {"job_id": job_id, "status": "complete_no_outreach", "report": values["report"]}

    return {"job_id": job_id, "status": status}


@router.get(
    "/jobs/{job_id}/report/download",
    tags=["Swarm Operations"],
    summary="4. Download Research Report File (.md)",
)
def download_job_report(job_id: str):
    reports_dir = "reports"
    if os.path.exists(reports_dir):
        files = [
            os.path.join(reports_dir, filename)
            for filename in os.listdir(reports_dir)
            if filename.endswith(".md")
        ]
        if files:
            files.sort(key=os.path.getmtime, reverse=True)
            return FileResponse(
                path=files[0],
                media_type="text/markdown",
                filename=f"research_report_{job_id[:8]}.md",
            )

    raise HTTPException(status_code=404, detail="Report file not found")


@router.post(
    "/jobs/{job_id}/approve",
    tags=["Outreach & HITL Approval"],
    summary="5. Approve or Discard Email Draft",
)
def approve_outreach(job_id: str, request: ApprovalRequest):
    if job_statuses.get(job_id) != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Job is not awaiting approval")

    values = job_states.get(job_id)
    if values is None:
        raise HTTPException(status_code=404, detail="Job not found")

    pending_review = get_pending_review(values)
    if not pending_review:
        raise HTTPException(status_code=400, detail="No draft awaiting approval for this job")

    update_vals = {"hitl_approved": request.approved}
    send_meta = {}

    if request.approved:
        to_email = request.to_email or pending_review.get("to_email")
        draft_text = pending_review.get("draft", "")
        subject, _, body = draft_text.partition("\n\n")
        subject = subject.replace("Subject: ", "").strip()

        if to_email:
            try:
                send_meta = gmail_client.send_message(
                    to_email=to_email,
                    subject=subject or "Outreach",
                    body=body or draft_text,
                )
            except Exception:
                send_meta = {}

        update_vals["to_email"] = to_email

    values.update(update_vals)
    for draft in values.get("drafts", {}).get("outreach", []):
        if isinstance(draft, dict) and draft.get("approved") is None:
            draft["approved"] = request.approved
            if update_vals.get("to_email"):
                draft["to_email"] = update_vals["to_email"]

    job_statuses[job_id] = "completed"

    return {
        "job_id": job_id,
        "status": "approved" if request.approved else "discarded",
        "to_email": update_vals.get("to_email"),
        "gmail_message": send_meta,
    }
