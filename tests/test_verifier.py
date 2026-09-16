import nodes.verifier as verifier_module
from nodes.verifier import ClaimVerdict, VerifierOutput, verifier_node
from schemas import Confidence, Contact, Finding, RejectionReason, VerifierStatus
from state import State


def _finding(id_="f1", claim="Acme raised $10M Series A", confidence=Confidence.MEDIUM):
    return Finding(
        id=id_,
        researcher_id="r1",
        src_link="https://example.com",
        snippet="Acme raised $10M",
        confidence=confidence,
        claim=claim,
    )


def test_verifier_node_returns_coverage_gap_penalty_when_nothing_found():
    state = State(job_id="j1", raw_query="q")

    result = verifier_node(state)

    assert result["verified_findings"] == []
    assert result["verified_contacts"] == []
    assert len(result["penalties"]) == 1
    assert result["penalties"][0].rejection_reason == RejectionReason.MISSING_EXPECTED


def test_verifier_node_marks_finding_verified(monkeypatch):
    finding = _finding()
    state = State(job_id="j1", raw_query="q", findings=[finding])

    fake_output = VerifierOutput(
        verdicts=[ClaimVerdict(id="f1", status="verified")],
        coverage_gap=None,
    )
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    assert len(result["verified_findings"]) == 1
    assert result["verified_findings"][0].verifier_status == VerifierStatus.VERIFIED
    assert result["penalties"] == []


def test_verifier_node_flags_unsupported_claim_as_penalty(monkeypatch):
    finding = _finding()
    state = State(job_id="j1", raw_query="q", findings=[finding])

    fake_output = VerifierOutput(
        verdicts=[ClaimVerdict(id="f1", status="flagged", rejection_reason="unsupported")],
        coverage_gap=None,
    )
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    # Flagged findings are dropped from verified_findings entirely, not carried
    # over with a FLAGGED status — but the shared Finding object is still
    # mutated in place before being excluded.
    assert result["verified_findings"] == []
    assert finding.verifier_status == VerifierStatus.FLAGGED
    assert len(result["penalties"]) == 1
    assert result["penalties"][0].rejection_reason == RejectionReason.UNSUPPORTED
    assert result["penalties"][0].id == "f1"


def test_verifier_node_low_relevance_is_still_verified(monkeypatch):
    """route_after_verifier only branches on penalties list length, but low_relevance
    findings should survive to the report rather than being discarded outright."""
    finding = _finding()
    state = State(job_id="j1", raw_query="q", findings=[finding])

    fake_output = VerifierOutput(
        verdicts=[ClaimVerdict(id="f1", status="flagged", rejection_reason="low_relevance")],
        coverage_gap=None,
    )
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    assert result["verified_findings"][0].verifier_status == VerifierStatus.VERIFIED
    assert result["penalties"] == []


def test_verifier_node_defaults_unmatched_finding_to_verified(monkeypatch):
    finding = _finding(id_="unmatched")
    state = State(job_id="j1", raw_query="q", findings=[finding])

    fake_output = VerifierOutput(verdicts=[], coverage_gap=None)
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    assert result["verified_findings"][0].verifier_status == VerifierStatus.VERIFIED


def test_verifier_node_adds_coverage_gap_penalty_when_no_contacts(monkeypatch):
    finding = _finding()
    state = State(job_id="j1", raw_query="q", findings=[finding])

    fake_output = VerifierOutput(
        verdicts=[ClaimVerdict(id="f1", status="verified")],
        coverage_gap="No decision maker identified",
    )
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    coverage_penalties = [p for p in result["penalties"] if p.id == "coverage_gap"]
    assert len(coverage_penalties) == 1


def test_verifier_node_skips_coverage_gap_penalty_when_contacts_present(monkeypatch):
    finding = _finding()
    contact = Contact(researcher_id="r1", src_link="https://example.com", snippet="s", confidence=Confidence.HIGH, name="Jane Doe")
    state = State(job_id="j1", raw_query="q", findings=[finding], contacts=[contact])

    fake_output = VerifierOutput(
        verdicts=[ClaimVerdict(id="f1", status="verified")],
        coverage_gap="No decision maker identified",
    )
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    assert all(p.id != "coverage_gap" for p in result["penalties"])
    assert result["verified_contacts"] == [contact]


def test_verifier_node_updates_confidence_when_provided(monkeypatch):
    finding = _finding(confidence=Confidence.LOW)
    state = State(job_id="j1", raw_query="q", findings=[finding])

    fake_output = VerifierOutput(
        verdicts=[ClaimVerdict(id="f1", status="verified", updated_confidence="high")],
        coverage_gap=None,
    )
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    assert result["verified_findings"][0].confidence == Confidence.HIGH


def test_verifier_node_falls_back_to_unsupported_on_bad_rejection_reason(monkeypatch):
    finding = _finding()
    state = State(job_id="j1", raw_query="q", findings=[finding])

    fake_output = VerifierOutput(
        verdicts=[ClaimVerdict(id="f1", status="flagged", rejection_reason=None)],
        coverage_gap=None,
    )
    monkeypatch.setattr(verifier_module.strong_llm, "generate", lambda **kwargs: fake_output)

    result = verifier_node(state)

    assert result["penalties"][0].rejection_reason == RejectionReason.UNSUPPORTED
