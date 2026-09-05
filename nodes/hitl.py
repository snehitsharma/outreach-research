# ============================================================
# nodes/hitl.py — Human-in-the-Loop Review Payload & Utilities
# ============================================================

from gmail_mcp_client import gmail_client


def get_pending_review(state) -> dict | None:
    """Returns the draft item currently awaiting human review from state."""
    values = getattr(state, "values", None) or state
    drafts = values.get("drafts") if isinstance(values, dict) else getattr(values, "drafts", {})

    for kind in ("follow_up", "outreach"):
        items = drafts.get(kind, []) if isinstance(drafts, dict) else getattr(drafts, kind, [])
        for item in items:
            approved = item.get("approved") if isinstance(item, dict) else getattr(item, "approved", None)
            if approved is None:
                draft_text = item.get("draft_text") if isinstance(item, dict) else getattr(item, "draft_text", None)
                body = item.get("body") if isinstance(item, dict) else getattr(item, "body", None)
                to_email = item.get("to_email") if isinstance(item, dict) else getattr(item, "to_email", None)
                recipient_name = item.get("recipient_name") if isinstance(item, dict) else getattr(item, "recipient_name", None)
                return {
                    "draft_type": kind,
                    "draft": draft_text or body or "",
                    "to_email": to_email,
                    "recipient_name": recipient_name,
                }
    return None


def get_human_review_payload(state) -> dict | None:
    """
    Formats the complete approval bundle for human review prior to sending:
    - Full structured report
    - List of extracted contacts
    - Target contact recommendation + explicit reason (who & why)
    - Proposed email draft
    """
    values = getattr(state, "values", None) or state
    if isinstance(values, dict):
        report = values.get("report")
        contacts = values.get("contacts") or []
        drafts = values.get("drafts") or {}
    else:
        report = getattr(values, "report", None)
        contacts = getattr(values, "contacts", None) or []
        drafts = getattr(values, "drafts", {}) or {}

    outreach_items = drafts.get("outreach") if isinstance(drafts, dict) else getattr(drafts, "outreach", [])
    if not outreach_items:
        return None

    draft_item = outreach_items[0] if isinstance(outreach_items, list) and outreach_items else {}
    if isinstance(draft_item, dict) and draft_item.get("approved") is not None:
        return None

    rec_contact = None
    rec_reason = None
    if report:
        rec_contact = getattr(report, "recommended_contact", None) or (report.get("recommended_contact") if isinstance(report, dict) else None)
        rec_reason = getattr(report, "recommended_contact_reason", None) or (report.get("recommended_contact_reason") if isinstance(report, dict) else None)

    return {
        "report": report,
        "all_contacts": contacts,
        "recommendation": {
            "target_contact": rec_contact or (contacts[0] if contacts else None),
            "reason": rec_reason or "Selected by synthesizer based on relevance to research goal.",
        },
        "draft": {
            "type": "outreach",
            "subject": draft_item.get("subject") if isinstance(draft_item, dict) else getattr(draft_item, "subject", None),
            "body": draft_item.get("body") if isinstance(draft_item, dict) else getattr(draft_item, "body", None),
            "to_email": draft_item.get("to_email") if isinstance(draft_item, dict) else getattr(draft_item, "to_email", None),
            "recipient_name": draft_item.get("recipient_name") if isinstance(draft_item, dict) else getattr(draft_item, "recipient_name", None),
            "gmail_draft_id": draft_item.get("gmail_draft_id") if isinstance(draft_item, dict) else getattr(draft_item, "gmail_draft_id", None),
            "gmail_thread_id": draft_item.get("gmail_thread_id") if isinstance(draft_item, dict) else getattr(draft_item, "gmail_thread_id", None),
        },
    }


def create_gmail_draft(state, to_email: str) -> str:
    """Create a Gmail draft for the current draft using gmail_mcp_client."""
    values = getattr(state, "values", None) or state
    drafts = values.get("drafts") if isinstance(values, dict) else getattr(values, "drafts", {})
    outreach = drafts.get("outreach") if isinstance(drafts, dict) else getattr(drafts, "outreach", [])

    if not outreach:
        return ""

    item = outreach[0] if isinstance(outreach, list) and outreach else {}
    subj = item.get("subject") if isinstance(item, dict) else getattr(item, "subject", "")
    body = item.get("body") if isinstance(item, dict) else getattr(item, "body", "")

    meta = gmail_client.create_draft(to_email=to_email, subject=subj, body=body)
    return meta.get("draft_id", "")