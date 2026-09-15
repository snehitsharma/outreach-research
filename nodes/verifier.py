from state import State
from schemas import Finding, Penalty, VerifierStatus, RejectionReason
from llm_clients import strong_llm
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
    findings = state.findings or []
    contacts = state.contacts or []

    if not findings and not contacts:
        return {
            "verified_findings": [],
            "verified_contacts": [],
            "penalties": [Penalty(
                id="coverage_gap",
                claim="No contacts surfaced in initial pass",
                src_link="",
                snippet="",
                rejection_reason=RejectionReason.MISSING_EXPECTED,
            )],
            "findings_verified": True,
        }


    result = strong_llm.generate(
        prompt=f"""You are verifying research findings before they go into a report.

        Original request: "{state.query}"
        Goal: "{state.goal or 'general'}"

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

    verdict_map = {v.id: v for v in result.verdicts if v.id}

    updated_findings = []
    new_penalties = []

    for f in findings:
        verdict = verdict_map.get(f.id)
        if verdict is None:
            f.verifier_status = VerifierStatus.VERIFIED
            updated_findings.append(f)
            continue

        
        if verdict.status == "verified" or verdict.rejection_reason == "low_relevance":
            f.verifier_status = VerifierStatus.VERIFIED
            
            if verdict.updated_confidence:
                f.confidence = verdict.updated_confidence
            updated_findings.append(f)
        else:
            f.verifier_status = VerifierStatus.FLAGGED
            try:
                rej_enum = RejectionReason(verdict.rejection_reason)
            except Exception:
                rej_enum = RejectionReason.UNSUPPORTED

            new_penalties.append(Penalty(
                id=f.id,
                claim=f.claim,
                src_link=f.src_link,
                snippet=f.snippet,
                rejection_reason=rej_enum,
            ))

    
    if result.coverage_gap and not contacts:
        new_penalties.append(Penalty(
            id="coverage_gap",
            claim=result.coverage_gap,
            src_link="",
            snippet="",
            rejection_reason=RejectionReason.MISSING_EXPECTED,
        ))

    return {
        "verified_findings": updated_findings,
        "verified_contacts": contacts,
        "penalties": new_penalties,
        "findings_verified": True,
    }


def _format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "(no findings to verify)"
    return "\n".join(
        f"[{f.id}] Claim: {f.claim} | Source: {f.src_link} | Snippet: {f.snippet}"
        for f in findings
    )