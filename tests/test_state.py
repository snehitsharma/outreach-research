import pytest
from pydantic import ValidationError

import schemas
from state import SanitizeMeta, State


def test_state_initial_builds_expected_defaults():
    result = State.initial(job_id="abc", raw_query="find leads", goal="hire")

    assert isinstance(result, State)
    assert result.job_id == "abc"
    assert result.raw_query == "find leads"
    assert result.goal == "hire"


def test_state_requires_job_id_and_raw_query():
    with pytest.raises(ValidationError):
        State()


def test_state_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        State(job_id="j1", raw_query="q", not_a_real_field=True)


def test_state_default_sanitize_meta_is_typed():
    state = State(job_id="j1", raw_query="q")
    assert isinstance(state.sanitize_meta, SanitizeMeta)
    assert state.sanitize_meta.was_truncated is False
    assert state.sanitize_meta.injection_flagged is False


def test_state_default_drafts_shape():
    state = State(job_id="j1", raw_query="q")
    assert state.drafts == {"outreach": [], "follow_up": []}


def test_state_no_longer_exposes_removed_fields():
    state = State(job_id="j1", raw_query="q")
    assert not hasattr(state, "contacts_enriched")
    assert not hasattr(state, "findings_verified")
    assert not hasattr(state, "hitl_approved")


def test_schemas_goal_enum_was_removed():
    assert not hasattr(schemas, "Goal")


def test_schemas_job_input_was_removed():
    assert not hasattr(schemas, "JobInput")


def test_draft_item_no_longer_has_sent_or_scheduled_for():
    draft = schemas.DraftItem(kind="outreach")
    assert not hasattr(draft, "sent")
    assert not hasattr(draft, "scheduled_for")


def test_approval_request_no_longer_has_recipient_name():
    approval = schemas.ApprovalRequest(approved=True)
    assert not hasattr(approval, "recipient_name")
