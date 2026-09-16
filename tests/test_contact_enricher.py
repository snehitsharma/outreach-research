import nodes.contact_enricher as contact_enricher_module
from nodes.contact_enricher import contact_enrichment_node
from schemas import Confidence, Contact
from state import State


def _contact(name="Jane Doe", email=None, role=None, company="Acme"):
    return Contact(
        researcher_id="r1",
        src_link="https://example.com",
        snippet="s",
        confidence=Confidence.HIGH,
        name=name,
        email=email,
        role=role,
        company=company,
    )


def test_skips_enrichment_when_not_sales_outreach(monkeypatch):
    called = False

    def fake_run(**kwargs):
        nonlocal called
        called = True
        return {"email": "x@x.com", "title": "CEO"}

    monkeypatch.setattr(contact_enricher_module.apollo_tool, "run", fake_run)

    state = State(job_id="j1", raw_query="q", is_sales_outreach=False, verified_contacts=[_contact(email=None)])
    result = contact_enrichment_node(state)

    assert called is False
    assert result["verified_contacts"] == state.verified_contacts


def test_returns_empty_when_no_contacts():
    state = State(job_id="j1", raw_query="q", is_sales_outreach=True, verified_contacts=[])
    result = contact_enrichment_node(state)
    assert result["verified_contacts"] == []


def test_enriches_contact_missing_email(monkeypatch):
    def fake_run(name, company):
        return {"email": "jane@acme.com", "title": "VP Sales"}

    monkeypatch.setattr(contact_enricher_module.apollo_tool, "run", fake_run)

    contact = _contact(name="Jane Doe", email=None, role=None)
    state = State(job_id="j1", raw_query="q", is_sales_outreach=True, verified_contacts=[contact])

    result = contact_enrichment_node(state)

    enriched = result["verified_contacts"][0]
    assert enriched.email == "jane@acme.com"
    assert enriched.role == "VP Sales"


def test_enriches_contact_with_na_email(monkeypatch):
    monkeypatch.setattr(
        contact_enricher_module.apollo_tool, "run", lambda name, company: {"email": "found@acme.com", "title": None}
    )

    contact = _contact(email="N/A")
    state = State(job_id="j1", raw_query="q", is_sales_outreach=True, verified_contacts=[contact])

    result = contact_enrichment_node(state)

    assert result["verified_contacts"][0].email == "found@acme.com"


def test_does_not_call_apollo_when_email_already_present(monkeypatch):
    called = False

    def fake_run(**kwargs):
        nonlocal called
        called = True
        return {"email": "should-not-be-used@x.com", "title": "X"}

    monkeypatch.setattr(contact_enricher_module.apollo_tool, "run", fake_run)

    contact = _contact(email="jane@acme.com", role="VP")
    state = State(job_id="j1", raw_query="q", is_sales_outreach=True, verified_contacts=[contact])

    result = contact_enrichment_node(state)

    assert called is False
    assert result["verified_contacts"][0].email == "jane@acme.com"


def test_does_not_overwrite_existing_role(monkeypatch):
    monkeypatch.setattr(
        contact_enricher_module.apollo_tool, "run", lambda name, company: {"email": "jane@acme.com", "title": "New Title"}
    )

    contact = _contact(email=None, role="Original Title")
    state = State(job_id="j1", raw_query="q", is_sales_outreach=True, verified_contacts=[contact])

    result = contact_enrichment_node(state)

    assert result["verified_contacts"][0].role == "Original Title"


def test_deduplicates_contacts_by_normalized_name(monkeypatch):
    monkeypatch.setattr(
        contact_enricher_module.apollo_tool, "run", lambda name, company: {"email": "x@x.com", "title": "T"}
    )

    contacts = [_contact(name="Jane Doe", email=None), _contact(name="  jane doe  ", email=None)]
    state = State(job_id="j1", raw_query="q", is_sales_outreach=True, verified_contacts=contacts)

    result = contact_enrichment_node(state)

    assert len(result["verified_contacts"]) == 1


def test_skips_contacts_without_a_name():
    contact = _contact(name="", email=None)
    state = State(job_id="j1", raw_query="q", is_sales_outreach=True, verified_contacts=[contact])

    result = contact_enrichment_node(state)

    assert result["verified_contacts"] == []
