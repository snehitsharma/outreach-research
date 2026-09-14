# ============================================================
# nodes/verifier.py — Telemetry Instrumented & Apollo Contact Enrichment
# ============================================================

from state import State
from schemas import Finding, Penalty, VerifierStatus, RejectionReason
from llm_clients import strong_llm
from tools import apollo_tool
from pydantic import BaseModel, Field
from typing import Literal


class ClaimVerdict(BaseModel):
    id: str = ""
    status: Literal["verified", "flagged"] = "verified"
    rejection_reason: Literal["unsupported", "missing_expected", "low_relevance", "contradicted"] | None = None
    updated_confidence: Literal["high", "medium", "low"] | None = None


class VerifierOutput(BaseModel):
    verdicts: list[ClaimVerdict] = Field(default_factory=list)
    coverage_gap: str | None = None


def verifier_node(state: State) -> dict:
    job_id = state.get("job_id") if isinstance(state, dict) else getattr(state, "job_id", None)
    findings = (state.get("findings") or []) if isinstance(state, dict) else (getattr(state, "findings", []) or [])
    contacts = (state.get("contacts") or []) if isinstance(state, dict) else (getattr(state, "contacts", []) or [])
    is_sales = state.get("is_sales_outreach", True) if isinstance(state, dict) else getattr(state, "is_sales_outreach", True)

    # Enrich contacts via Apollo API if sales outreach is active (deduplicated by name)
    if is_sales and contacts:
        enriched_contacts = []
        seen_names = set()
        for c in contacts:
            c_name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None)
            if not c_name:
                continue
            norm_name = c_name.strip().lower()
            if norm_name in seen_names:
                continue
            seen_names.add(norm_name)

            c_email = getattr(c, "email", None) or (c.get("email") if isinstance(c, dict) else None)
            if not c_email or c_email == "N/A":
                apollo_res = apollo_tool.run(name=c_name, company="Google")
                if isinstance(c, dict):
                    c["email"] = apollo_res.get("email")
                    if not c.get("role"):
                        c["role"] = apollo_res.get("title")
                else:
                    c.email = apollo_res.get("email")
                    if not getattr(c, "role", None):
                        c.role = apollo_res.get("title")
            enriched_contacts.append(c)
        contacts = enriched_contacts

    if not findings and not contacts:
        return {
            "findings": [],
            "penalties": [Penalty(
                id="coverage_gap",
                claim="No contacts surfaced in initial pass",
                src_link="",
                snippet="",
                rejection_reason=RejectionReason.MISSING_EXPECTED,
            )],
        }

    query = state.get("query", "") if isinstance(state, dict) else getattr(state, "query", "")
    goal = state.get("goal") if isinstance(state, dict) else getattr(state, "goal", None)

    result = strong_llm.generate(
        prompt=f"""You are verifying research findings before they go into a report.

        Original request: "{query}"
        Goal: "{goal or 'general'}"

        For each finding below, check three things:
        1. Fact-check: does the snippet actually support the claim?
        2. Contradiction: does this claim conflict with another finding in the list?
        3. Relevance: is this claim actually useful given the goal?

        Mark "verified" unless the claim is explicitly contradicted or completely unsupported.

        Findings:
        {_format_findings(findings)}

        Contacts found: {len(contacts)}
        """,
        response_model=VerifierOutput,
    )

    verdicts_list = getattr(result, "verdicts", []) or []
    verdict_map = {getattr(v, "id", ""): v for v in verdicts_list if getattr(v, "id", None)}

    updated_findings = []
    new_penalties = []

    for f in findings:
        verdict = verdict_map.get(f.id)
        if verdict is None:
            f.verifier_status = VerifierStatus.VERIFIED
            updated_findings.append(f)
            continue

        status = getattr(verdict, "status", "verified")
        rej_reason_str = getattr(verdict, "rejection_reason", None) or "unsupported"

        if status == "verified" or rej_reason_str == "low_relevance":
            f.verifier_status = VerifierStatus.VERIFIED
            up_conf = getattr(verdict, "updated_confidence", None)
            if up_conf:
                f.confidence = up_conf
            updated_findings.append(f)
        else:
            f.verifier_status = VerifierStatus.FLAGGED
            try:
                rej_enum = RejectionReason(rej_reason_str)
            except Exception:
                rej_enum = RejectionReason.UNSUPPORTED

            new_penalties.append(Penalty(
                id=f.id,
                claim=f.claim,
                src_link=f.src_link,
                snippet=f.snippet,
                rejection_reason=rej_enum,
            ))

    cov_gap = getattr(result, "coverage_gap", None)
    if cov_gap and not contacts:
        new_penalties.append(Penalty(
            id="coverage_gap",
            claim=cov_gap,
            src_link="",
            snippet="",
            rejection_reason=RejectionReason.MISSING_EXPECTED,
        ))

    return {"findings": updated_findings, "contacts": contacts, "penalties": new_penalties}


def _format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "(no findings to verify)"
    return "\n".join(
        f"[{f.id}] Claim: {f.claim} | Source: {f.src_link} | Snippet: {f.snippet}"
        for f in findings
    )