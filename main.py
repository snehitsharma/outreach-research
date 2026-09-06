# ============================================================
# main.py — Clean, Portfolio-Ready FastAPI Agent System
# ============================================================

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from pydantic import BaseModel, Field
from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore

from graph import build_graph
from config import config
from nodes.hitl import get_human_review_payload, get_pending_review
from events import events_manager
from gmail_mcp_client import gmail_client


app = FastAPI(
    title="Autonomous Research Swarm API",
    version="1.0.0",
    description="""
### Real-Time Multi-Agent Telemetry & Research Swarm API

This API orchestrates an autonomous AI agent swarm to perform parallel web research, contact discovery, executive report synthesis, and human-in-the-loop (HITL) outreach drafting.

- **Interactive API Documentation**: Access `/docs` for Swagger UI.
- **SSE Telemetry**: Subscribe to `/jobs/{job_id}/stream` for live agent activity feeds.
    """,
    openapi_tags=[
        {"name": "Swarm Operations", "description": "Endpoints to trigger research jobs, stream live logs, and fetch reports."},
        {"name": "Outreach & HITL Approval", "description": "Endpoints to review, approve, or discard drafted emails."},
    ]
)

# ---------- SQLite Persistence & Checkpointer ----------

DB_FILE = os.environ.get("SQLITE_DB_PATH", "state.db")

try:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
except Exception as e:
    print(f"[SQLite Checkpointer] Fallback to in-memory checkpointer: {e}")
    from langgraph.checkpoint.memory import MemorySaver  # type: ignore
    conn = None
    checkpointer = MemorySaver()

# Build the state machine graph once on server startup
graph = build_graph(checkpointer)


# ---------- Pydantic Request & Response Schemas ----------

class JobRequest(BaseModel):
    query: str = Field(
        ...,
        description="The research topic or prompt to investigate",
        json_schema_extra={"example": "Research Google Software Engineer hiring for 2 YOE and find recruiter contacts"}
    )
    goal: str | None = Field(
        default=None,
        description="Optional goal for target outreach or synthesis focus",
        json_schema_extra={"example": "Identify technical recruiters for candidate outreach"}
    )


class JobResponse(BaseModel):
    job_id: str
    status: str


class ApprovalRequest(BaseModel):
    approved: bool = Field(..., description="True to approve & send via Gmail, False to discard")
    to_email: str | None = Field(default=None, description="Target recipient email address")
    recipient_name: str | None = Field(default=None, description="Recipient full name")


def _resolve_status(state) -> str:
    values = getattr(state, "values", None) or state

    if not values.get("guardrail_passed", True) and values.get("guardrail_reason"):
        return "rejected"

    if get_pending_review(values):
        return "awaiting_approval"

    if values.get("report") and not (values.get("drafts") or {}).get("outreach"):
        return "complete_no_outreach"

    return "processing"


# ---------- API Routes ----------

@app.get("/", include_in_schema=False)
def index():
    """Redirect root endpoint to Swagger UI documentation."""
    return RedirectResponse(url="/docs")


@app.post("/jobs", response_model=JobResponse, tags=["Swarm Operations"], summary="1. Trigger Autonomous Research Job")
def trigger_job(request: JobRequest):
    job_id = str(uuid.uuid4())
    config_dict = {"configurable": {"thread_id": job_id}}

    initial_state = {
        "job_id": job_id,
        "raw_query": request.query,
        "query": "",
        "goal": request.goal,
        "guardrail_passed": False,
    }

    events_manager.emit(
        job_id=job_id,
        node="system",
        event_type="job_start",
        message=f"Research job initialized: '{request.query}'",
        payload={"query": request.query, "goal": request.goal},
    )

    # Invoke graph synchronously up to the HITL interrupt or completion point
    graph.invoke(initial_state, config=config_dict)
    state = graph.get_state(config_dict)

    if conn:
        try:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO jobs (job_id, thread_id) VALUES (?, ?)",
                    (job_id, job_id),
                )
        except Exception:
            pass

    status = _resolve_status(state)
    return JobResponse(job_id=job_id, status=status)


@app.get("/jobs/{job_id}/stream", tags=["Swarm Operations"], summary="2. Live SSE Telemetry Log Stream")
async def stream_job_events(job_id: str):
    """
    Streams real-time Server-Sent Events (SSE) detailing agent thoughts, Tavily API calls, and scraper traces.
    """
    return StreamingResponse(
        events_manager.subscribe(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/jobs/{job_id}", tags=["Swarm Operations"], summary="3. Get Job Results & Executive Report")
def get_job_result(job_id: str):
    """
    Polls state for the current status, executive research report, discovered contacts, and drafted outreach email.
    """
    config_dict = {"configurable": {"thread_id": job_id}}
    state = graph.get_state(config_dict)

    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    values = state.values
    pending_review = get_pending_review(values)

    if not values.get("guardrail_passed", True) and values.get("guardrail_reason"):
        return {"job_id": job_id, "status": "rejected", "reason": values["guardrail_reason"]}

    if pending_review:
        review_payload = get_human_review_payload(state)
        return {
            "job_id": job_id,
            "status": "awaiting_approval",
            "review_payload": review_payload,
            "draft": pending_review,
            "report": values.get("report"),
            "all_contacts": values.get("contacts"),
        }

    if values.get("report") and not (values.get("drafts") or {}).get("outreach"):
        return {"job_id": job_id, "status": "complete_no_outreach", "report": values["report"]}

    return {"job_id": job_id, "status": "processing"}


@app.get("/jobs/{job_id}/report/download", tags=["Swarm Operations"], summary="4. Download Research Report File (.md)")
def download_job_report(job_id: str):
    """
    Downloads the compiled markdown research report file directly to the client.
    """
    reports_dir = "reports"
    if os.path.exists(reports_dir):
        files = [os.path.join(reports_dir, f) for f in os.listdir(reports_dir) if f.endswith(".md")]
        if files:
            files.sort(key=os.path.getmtime, reverse=True)
            return FileResponse(
                path=files[0],
                media_type="text/markdown",
                filename=f"research_report_{job_id[:8]}.md"
            )

    raise HTTPException(status_code=404, detail="Report file not found")


@app.post("/jobs/{job_id}/approve", tags=["Outreach & HITL Approval"], summary="5. Approve or Discard Email Draft")
def approve_outreach(job_id: str, request: ApprovalRequest):
    """
    Human-in-the-Loop (HITL) approval endpoint to approve sending the drafted outreach email via Gmail or discard it.
    """
    config_dict = {"configurable": {"thread_id": job_id}}
    state = graph.get_state(config_dict)

    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    values = state.values
    pending_review = get_pending_review(values)
    if not pending_review:
        raise HTTPException(status_code=400, detail="No draft awaiting approval for this job")

    update_vals = {"hitl_approved": request.approved}
    send_meta = {}

    if request.approved:
        to_email = request.to_email or pending_review.get("to_email")
        recipient_name = request.recipient_name or pending_review.get("recipient_name")
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

    graph.update_state(config_dict, update_vals)
    result = graph.invoke(None, config=config_dict)

    events_manager.emit(
        job_id=job_id,
        node="system",
        event_type="job_complete",
        message=f"HITL Decision: {'APPROVED & SENT' if request.approved else 'DISCARDED'}",
    )

    return {
        "job_id": job_id,
        "status": "approved" if request.approved else "discarded",
        "to_email": update_vals.get("to_email"),
        "gmail_message": send_meta,
    }


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}