from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.types import Command

from dependencies import get_graph
from routers import jobs as jobs_module
from routers.jobs import router as jobs_router
from schemas import Confidence, Contact, DraftItem, Report
from state import State


def _make_app(fake_graph):
    app = FastAPI()
    app.include_router(jobs_router)
    app.dependency_overrides[get_graph] = lambda: fake_graph
    return app


def _client(fake_graph):
    return TestClient(_make_app(fake_graph))


def _completed_state(job_id, **overrides):
    base = State(job_id=job_id, raw_query="find leads at Acme", guardrail_passed=True)
    return base.model_copy(update=overrides)


# ---------- POST /jobs ----------

def test_trigger_job_runs_in_background_and_returns_pending():
    result_state = _completed_state("placeholder", report=Report(summary="sum", findings_by_theme={}))
    fake_graph = MagicMock()
    fake_graph.invoke.return_value = result_state.model_dump()
    fake_graph.get_state.return_value = MagicMock(next=None)

    client = _client(fake_graph)
    response = client.post("/jobs", json={"query": "find leads at Acme", "goal": "sales"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    job_id = body["job_id"]

    # TestClient runs BackgroundTasks synchronously before returning, so the
    # in-memory registries should already reflect the completed run.
    assert jobs_module.job_statuses[job_id] == "complete_no_outreach"
    fake_graph.invoke.assert_called_once()


def test_trigger_job_marks_failed_on_exception():
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = RuntimeError("boom")

    client = _client(fake_graph)
    response = client.post("/jobs", json={"query": "find leads"})

    job_id = response.json()["job_id"]
    assert jobs_module.job_statuses[job_id] == "failed"


# ---------- GET /jobs/{job_id} ----------

def test_get_job_result_404_when_unknown():
    client = _client(MagicMock())
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


def test_get_job_result_returns_status_only_before_state_exists():
    jobs_module.job_statuses["j1"] = "pending"
    client = _client(MagicMock())

    response = client.get("/jobs/j1")

    assert response.status_code == 200
    assert response.json() == {"job_id": "j1", "status": "pending"}


def test_get_job_result_rejected():
    jobs_module.job_statuses["j1"] = "rejected"
    jobs_module.job_states["j1"] = _completed_state("j1", guardrail_passed=False, guardrail_reason="off topic")

    client = _client(MagicMock())
    response = client.get("/jobs/j1")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["reason"] == "off topic"


def test_get_job_result_awaiting_approval_includes_review_payload():
    contact = Contact(researcher_id="r1", src_link="https://x.com", snippet="s", confidence=Confidence.HIGH, name="Jane Doe")
    draft = DraftItem(kind="outreach", subject="Hi", body="body", approved=None)
    state = _completed_state(
        "j1",
        report=Report(summary="sum", findings_by_theme={}),
        verified_contacts=[contact],
        drafts={"outreach": [draft], "follow_up": []},
    )
    jobs_module.job_statuses["j1"] = "awaiting_approval"
    jobs_module.job_states["j1"] = state

    client = _client(MagicMock())
    response = client.get("/jobs/j1")

    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["review_payload"]["draft"]["subject"] == "Hi"
    assert body["draft"]["draft_type"] == "outreach"


def test_get_job_result_complete_no_outreach():
    state = _completed_state("j1", report=Report(summary="sum", findings_by_theme={}))
    jobs_module.job_statuses["j1"] = "complete_no_outreach"
    jobs_module.job_states["j1"] = state

    client = _client(MagicMock())
    response = client.get("/jobs/j1")

    body = response.json()
    assert body["status"] == "complete_no_outreach"
    assert body["report"]["summary"] == "sum"


# ---------- GET /jobs/{job_id}/report/download ----------

def test_download_report_404_when_state_missing():
    client = _client(MagicMock())
    response = client.get("/jobs/nope/report/download")
    assert response.status_code == 404


def test_download_report_404_when_file_missing():
    state = _completed_state("j1", report_filepath="/nonexistent/report.md")
    jobs_module.job_states["j1"] = state

    client = _client(MagicMock())
    response = client.get("/jobs/j1/report/download")

    assert response.status_code == 404


def test_download_report_returns_file(tmp_path):
    report_file = tmp_path / "report.md"
    report_file.write_text("# Report", encoding="utf-8")

    state = _completed_state("j1", report_filepath=str(report_file))
    jobs_module.job_states["j1"] = state

    client = _client(MagicMock())
    response = client.get("/jobs/j1/report/download")

    assert response.status_code == 200
    assert response.text == "# Report"


# ---------- POST /jobs/{job_id}/approve ----------

def test_approve_400_when_not_awaiting_approval():
    jobs_module.job_statuses["j1"] = "processing"
    client = _client(MagicMock())

    response = client.post("/jobs/j1/approve", json={"approved": True})

    assert response.status_code == 400


def test_approve_404_when_state_missing():
    jobs_module.job_statuses["j1"] = "awaiting_approval"
    client = _client(MagicMock())

    response = client.post("/jobs/j1/approve", json={"approved": True})

    assert response.status_code == 404


def test_approve_400_when_no_pending_draft():
    jobs_module.job_statuses["j1"] = "awaiting_approval"
    jobs_module.job_states["j1"] = _completed_state("j1")

    client = _client(MagicMock())
    response = client.post("/jobs/j1/approve", json={"approved": True})

    assert response.status_code == 400


def test_approve_follow_up_resolves_without_graph_resume():
    followup = DraftItem(kind="follow_up", draft_text="following up", approved=None)
    state = _completed_state("j1", drafts={"outreach": [], "follow_up": [followup]})
    jobs_module.job_statuses["j1"] = "awaiting_approval"
    jobs_module.job_states["j1"] = state

    fake_graph = MagicMock()
    client = _client(fake_graph)
    response = client.post("/jobs/j1/approve", json={"approved": True, "to_email": "lead@company.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["to_email"] == "lead@company.com"
    fake_graph.invoke.assert_not_called()
    assert jobs_module.job_statuses["j1"] == "completed"
    assert jobs_module.job_states["j1"].drafts["follow_up"][0].approved is True


def test_approve_outreach_resumes_graph():
    outreach = DraftItem(kind="outreach", draft_text="hi", to_email="lead@company.com", approved=None)
    state = _completed_state("j1", drafts={"outreach": [outreach], "follow_up": []})
    jobs_module.job_statuses["j1"] = "awaiting_approval"
    jobs_module.job_states["j1"] = state

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=("hitl_wait",))
    fake_graph.invoke.return_value = state.model_dump()

    client = _client(fake_graph)
    response = client.post("/jobs/j1/approve", json={"approved": True, "to_email": "lead@company.com"})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert jobs_module.job_statuses["j1"] == "completed"

    invoke_args = fake_graph.invoke.call_args
    resume_command = invoke_args[0][0]
    assert isinstance(resume_command, Command)


def test_approve_outreach_404_when_graph_not_paused():
    outreach = DraftItem(kind="outreach", draft_text="hi", approved=None)
    state = _completed_state("j1", drafts={"outreach": [outreach], "follow_up": []})
    jobs_module.job_statuses["j1"] = "awaiting_approval"
    jobs_module.job_states["j1"] = state

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=None)

    client = _client(fake_graph)
    response = client.post("/jobs/j1/approve", json={"approved": False})

    assert response.status_code == 404
