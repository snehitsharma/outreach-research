import nodes.hitl as hitl_module
from nodes.hitl import create_gmail_draft, get_human_review_payload, get_pending_review
from schemas import Confidence, Contact, DraftItem, Report
from state import State


def test_get_pending_review_returns_none_when_no_drafts():
    state = State(job_id="j1", raw_query="q")
    assert get_pending_review(state) is None


def test_get_pending_review_finds_unapproved_outreach():
    draft = DraftItem(kind="outreach", draft_text="hi", to_email="a@b.com", approved=None)
    state = State(job_id="j1", raw_query="q", drafts={"outreach": [draft], "follow_up": []})

    result = get_pending_review(state)

    assert result["draft_type"] == "outreach"
    assert result["to_email"] == "a@b.com"


def test_get_pending_review_prefers_follow_up_over_outreach():
    outreach_draft = DraftItem(kind="outreach", draft_text="hi", approved=None)
    followup_draft = DraftItem(kind="follow_up", draft_text="following up", approved=None)
    state = State(
        job_id="j1",
        raw_query="q",
        drafts={"outreach": [outreach_draft], "follow_up": [followup_draft]},
    )

    result = get_pending_review(state)

    assert result["draft_type"] == "follow_up"


def test_get_pending_review_returns_none_when_already_approved():
    draft = DraftItem(kind="outreach", draft_text="hi", approved=True)
    state = State(job_id="j1", raw_query="q", drafts={"outreach": [draft], "follow_up": []})

    assert get_pending_review(state) is None


def test_get_human_review_payload_returns_none_without_outreach_items():
    state = State(job_id="j1", raw_query="q")
    assert get_human_review_payload(state) is None


def test_get_human_review_payload_returns_none_when_already_decided():
    draft = DraftItem(kind="outreach", subject="s", body="b", approved=False)
    state = State(job_id="j1", raw_query="q", drafts={"outreach": [draft], "follow_up": []})

    assert get_human_review_payload(state) is None


def test_get_human_review_payload_builds_expected_shape():
    contact = Contact(researcher_id="r1", src_link="https://x.com", snippet="s", confidence=Confidence.HIGH, name="Jane Doe")
    report = Report(summary="summary text", findings_by_theme={}, recommended_contact=contact, recommended_contact_reason="best fit")
    draft = DraftItem(kind="outreach", subject="Hello", body="body text", to_email="jane@x.com", to_name="Jane Doe", approved=None)

    state = State(
        job_id="j1",
        raw_query="q",
        report=report,
        verified_contacts=[contact],
        drafts={"outreach": [draft], "follow_up": []},
    )

    payload = get_human_review_payload(state)

    assert payload["report"] is report
    assert payload["all_contacts"] == [contact]
    assert payload["recommendation"]["target_contact"] == contact
    assert payload["recommendation"]["reason"] == "best fit"
    assert payload["draft"]["subject"] == "Hello"
    assert payload["draft"]["to_email"] == "jane@x.com"


def test_get_human_review_payload_falls_back_to_first_contact_when_no_recommendation():
    contact = Contact(researcher_id="r1", src_link="https://x.com", snippet="s", confidence=Confidence.HIGH, name="Jane Doe")
    draft = DraftItem(kind="outreach", subject="Hello", body="body", approved=None)

    state = State(
        job_id="j1",
        raw_query="q",
        report=None,
        verified_contacts=[contact],
        drafts={"outreach": [draft], "follow_up": []},
    )

    payload = get_human_review_payload(state)

    assert payload["recommendation"]["target_contact"] == contact
    assert "Selected by synthesizer" in payload["recommendation"]["reason"]


def test_create_gmail_draft_returns_empty_string_without_outreach_drafts():
    state = State(job_id="j1", raw_query="q")
    assert create_gmail_draft(state, "a@b.com") == ""


def test_create_gmail_draft_calls_gmail_client(monkeypatch):
    captured = {}

    def fake_create_draft(**kwargs):
        captured.update(kwargs)
        return {"draft_id": "draft_123"}

    monkeypatch.setattr(hitl_module.gmail_client, "create_draft", fake_create_draft)

    draft = DraftItem(kind="outreach", subject="Hi", body="Body text", approved=True)
    state = State(job_id="j1", raw_query="q", drafts={"outreach": [draft], "follow_up": []})

    draft_id = create_gmail_draft(state, "target@company.com")

    assert draft_id == "draft_123"
    assert captured["to_email"] == "target@company.com"
    assert captured["subject"] == "Hi"
    assert captured["body"] == "Body text"
