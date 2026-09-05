# ============================================================
# nodes/outreach_drafter.py — Telemetry Instrumented
# ============================================================

from pydantic import BaseModel
from state import State
from llm_clients import mid_llm
from gmail_mcp_client import gmail_client
from events import events_manager


class OutreachDraft(BaseModel):
    subject: str
    body: str


def outreach_drafter_node(state: State) -> dict:
    """LangGraph node: generates initial outreach email draft based on recommended target contact."""
    job_id = state.get("job_id") if isinstance(state, dict) else getattr(state, "job_id", None)
    report = state.get("report") if isinstance(state, dict) else getattr(state, "report", None)
    contacts = (state.get("contacts") or []) if isinstance(state, dict) else (getattr(state, "contacts", []) or [])

    if job_id:
        events_manager.emit(job_id, "outreach_drafter", "thinking", "Drafting candidate outreach email...")

    if not report or not contacts:
        if job_id:
            events_manager.emit(job_id, "outreach_drafter", "complete", "No target contacts surfaced; skipped draft generation.")
        return {"drafts": {"outreach": []}}

    target_contact = getattr(report, "recommended_contact", None) or contacts[0]
    query = state.get("query", "") if isinstance(state, dict) else getattr(state, "query", "")
    goal = state.get("goal") if isinstance(state, dict) else getattr(state, "goal", None)

    result = mid_llm.generate(
        prompt=(
            f"Draft a short, tailored outreach email for {target_contact.name} ({target_contact.role or 'role unknown'}). "
            f"Context: {query}. Report summary: {report.summary}. Goal: {goal or 'outreach'}."
        ),
        response_model=OutreachDraft,
    )

    subject = getattr(result, "subject", "") or f"Re: {query or 'Outreach'}"
    body = getattr(result, "body", "") or f"Hi {target_contact.name},\n\nI noticed your work as {target_contact.role or 'leader'} and wanted to connect regarding {query}."
    draft_text = f"Subject: {subject}\n\n{body}"

    to_email = getattr(target_contact, "email", None)
    gmail_meta = {}
    if to_email:
        try:
            gmail_meta = gmail_client.create_draft(to_email=to_email, subject=subject, body=body)
        except Exception:
            gmail_meta = {}

    if job_id:
        events_manager.emit(
            job_id,
            "outreach_drafter",
            "complete",
            f"Drafted email for {target_contact.name} ({to_email or 'no email'}). Awaiting HITL human review.",
            payload={"recipient": target_contact.name, "to_email": to_email, "subject": subject},
        )

    return {
        "drafts": {
            "outreach": [{
                "kind": "outreach",
                "draft_text": draft_text,
                "subject": subject,
                "body": body,
                "to_email": to_email,
                "recipient_name": getattr(target_contact, "name", None),
                "gmail_draft_id": gmail_meta.get("draft_id"),
                "gmail_message_id": gmail_meta.get("message_id"),
                "gmail_thread_id": gmail_meta.get("thread_id"),
                "approved": None,
            }]
        }
    }


def draft_followup(state: State) -> dict:
    """Generates a follow-up draft for pending follow-up schedules."""
    job_id = state.get("job_id") if isinstance(state, dict) else getattr(state, "job_id", None)
    drafts = (state.get("drafts") or {}) if isinstance(state, dict) else (getattr(state, "drafts", {}) or {})
    outreach_items = drafts.get("outreach", [])
    prior = next((d.get("draft_text") for d in outreach_items if isinstance(d, dict) and d.get("approved") is True), None)

    if not prior:
        return {"drafts": {"follow_up": []}}

    result = mid_llm.generate(
        prompt=f"Write a polite, concise follow-up email referencing prior outreach. Prior context: {prior}",
        response_model=OutreachDraft,
    )

    subject = getattr(result, "subject", "") or "Following up on outreach"
    body = getattr(result, "body", "") or "Hi, following up on our previous note to see if you have any questions!"
    followup_text = f"Subject: {subject}\n\n{body}"

    to_email = outreach_items[0].get("to_email") if outreach_items and isinstance(outreach_items[0], dict) else None

    gmail_meta = {}
    if to_email:
        try:
            gmail_meta = gmail_client.create_draft(to_email=to_email, subject=subject, body=body)
        except Exception:
            gmail_meta = {}

    if job_id:
        events_manager.emit(
            job_id,
            "outreach_drafter",
            "complete",
            f"Generated follow-up draft for {to_email or 'recipient'}.",
            payload={"to_email": to_email, "subject": subject},
        )

    return {
        "drafts": {
            "follow_up": [{
                "kind": "follow_up",
                "draft_text": followup_text,
                "subject": subject,
                "body": body,
                "to_email": to_email,
                "gmail_draft_id": gmail_meta.get("draft_id"),
                "gmail_message_id": gmail_meta.get("message_id"),
                "gmail_thread_id": gmail_meta.get("thread_id"),
                "approved": None,
            }]
        }
    }
