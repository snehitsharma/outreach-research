

from pydantic import BaseModel
from state import State
from schemas import DraftItem
from llm_clients import mid_llm
from gmail_mcp_client import gmail_client


class OutreachDraft(BaseModel):
    subject: str
    body: str


def outreach_drafter_node(state: State) -> dict:
    """Generates initial outreach email draft based on recommended target contact."""
    report = state.report
    contacts = state.verified_contacts or []

    if not report or not contacts:
        return {"drafts": {"outreach": [], "follow_up": []}}

    target_contact = report.recommended_contact or contacts[0]
    query = state.query
    goal = state.goal

    result = mid_llm.generate(
        prompt=(
            f"Draft a short, tailored outreach email for {target_contact.name} ({target_contact.role or 'role unknown'}). "
            f"Context: {query}. Report summary: {report.summary}. Goal: {goal or 'outreach'}."
        ),
        response_model=OutreachDraft,
    )

    subject = result.subject or f"Re: {query or 'Outreach'}"
    body = result.body or f"Hi {target_contact.name},\n\nI noticed your work as {target_contact.role or 'leader'} and wanted to connect regarding {query}."
    draft_text = f"Subject: {subject}\n\n{body}"

    to_email = target_contact.email
    gmail_meta = {}
    if to_email:
        try:
            gmail_meta = gmail_client.create_draft(to_email=to_email, subject=subject, body=body)
        except Exception:
            gmail_meta = {}

    draft = DraftItem(
        kind="outreach",
        subject=subject,
        body=body,
        draft_text=draft_text,
        to_email=to_email,
        to_name=target_contact.name,
        gmail_draft_id=gmail_meta.get("draft_id"),
        gmail_message_id=gmail_meta.get("message_id"),
        gmail_thread_id=gmail_meta.get("thread_id"),
        approved=None,
    )

    return {"drafts": {"outreach": [draft], "follow_up": []}}


def draft_followup(state: State) -> dict:
    outreach_items = state.drafts.get("outreach", [])
    prior = next((d.draft_text for d in outreach_items if d.approved is True), None)

    if not prior:
        return {"drafts": {"follow_up": []}}

    result = mid_llm.generate(
        prompt=f"Write a polite, concise follow-up email referencing prior outreach. Prior context: {prior}",
        response_model=OutreachDraft,
    )

    subject = result.subject or "Following up on outreach"
    body = result.body or "Hi, following up on our previous note to see if you have any questions!"
    followup_text = f"Subject: {subject}\n\n{body}"

    to_email = outreach_items[0].to_email if outreach_items else None

    gmail_meta = {}
    if to_email:
        try:
            gmail_meta = gmail_client.create_draft(to_email=to_email, subject=subject, body=body)
        except Exception:
            gmail_meta = {}

    draft = DraftItem(
        kind="follow_up",
        subject=subject,
        body=body,
        draft_text=followup_text,
        to_email=to_email,
        gmail_draft_id=gmail_meta.get("draft_id"),
        gmail_message_id=gmail_meta.get("message_id"),
        gmail_thread_id=gmail_meta.get("thread_id"),
        approved=None,
    )

    return {"drafts": {"follow_up": [draft]}}
