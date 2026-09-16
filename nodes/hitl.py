# nodes/hitl.py — Human-in-the-Loop Review Payload & Utilities
from gmail_mcp_client import gmail_client


def get_pending_review(state_values) -> dict | None:
   
    drafts = state_values.drafts or {}

    for kind in ("follow_up", "outreach"):
        for item in drafts.get(kind, []):
            if item.approved is None:
                return {
                    "draft_type": kind,
                    "draft": item.draft_text or item.body or "",
                    "to_email": item.to_email,
                    "to_name": item.to_name,
                }
    return None


def get_human_review_payload(state_values) -> dict | None:
   
    report = state_values.report
    contacts = state_values.verified_contacts or []
    drafts = state_values.drafts or {}

    outreach_items = drafts.get("outreach", [])
    if not outreach_items:
        return None

    draft_item = outreach_items[0]
    if draft_item.approved is not None:
        return None

    rec_contact = report.recommended_contact if report else None
    rec_reason = report.recommended_contact_reason if report else None

    return {
        "report": report,
        "all_contacts": contacts,
        "recommendation": {
            "target_contact": rec_contact or (contacts[0] if contacts else None),
            "reason": rec_reason or "Selected by synthesizer based on relevance to research goal.",
        },
        "draft": {
            "type": "outreach",
            "subject": draft_item.subject,
            "body": draft_item.body,
            "to_email": draft_item.to_email,
            "to_name": draft_item.to_name,
            "gmail_draft_id": draft_item.gmail_draft_id,
            "gmail_thread_id": draft_item.gmail_thread_id,
        },
    }


def create_gmail_draft(state_values, to_email: str) -> str:
    """Create a Gmail draft once a human has approved — called from the /approve route."""
    outreach = state_values.drafts.get("outreach", [])
    if not outreach:
        return ""

    item = outreach[0]
    meta = gmail_client.create_draft(to_email=to_email, subject=item.subject, body=item.body)
    return meta.get("draft_id", "")