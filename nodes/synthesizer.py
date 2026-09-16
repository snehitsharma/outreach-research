# ============================================================
# nodes/synthesizer.py — Research Report Generator & Disk Persistence
# ============================================================

import os
import json
import uuid
from datetime import datetime, timezone
from state import State
from schemas import Report
from llm_clients import mid_llm
from pydantic import BaseModel, Field


class ThemeNarrative(BaseModel):
    heading: str = Field(default="Analysis Section", description="Section title or heading")
    paragraph: str = Field(default="", description="A clear, cohesive prose paragraph synthesizing findings without bullet lists or duplicated sentences.")


class SynthesizerOutput(BaseModel):
    executive_summary: str = Field(..., description="High-level narrative summary (2-3 well-written paragraphs)")
    sections: list[ThemeNarrative] = Field(..., description="Key analysis sections formatted in executive prose")
    recommended_contact_name: str = Field(default="", description="Name of the best target contact")
    recommended_contact_reason: str = Field(default="", description="Justification for selecting this contact")


def _deduplicate_findings(findings: list) -> list:
    """Deduplicates findings by claim content to prevent repeated sentences."""
    seen = set()
    unique = []
    for f in findings:
        claim_text = getattr(f, "claim", None) or (f.get("claim") if isinstance(f, dict) else str(f))
        norm = claim_text.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(f)
    return unique


def _deduplicate_contacts(contacts: list) -> list:
    """Deduplicates contacts by full name."""
    seen = set()
    unique = []
    for c in contacts:
        name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None)
        if not name:
            continue
        norm = name.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(c)
    return unique


def _save_report_to_disk(report: Report, query: str, sections: list[ThemeNarrative]) -> str:
    """Saves generated research report to reports/ directory on disk in executive prose markdown format."""
    try:
        os.makedirs("reports", exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_id = uuid.uuid4().hex[:8]
        filename = f"reports/report_{timestamp}_{report_id}.md"

        md_content = f"# Research Brief: {query}\n\n"
        md_content += f"**Date:** {datetime.now(timezone.utc).strftime('%B %d, %Y')}\n\n"
        md_content += f"## Executive Summary\n\n{report.summary}\n\n"

        if report.recommended_contact:
            c = report.recommended_contact
            md_content += f"## Recommended Target Contact\n\n"
            md_content += f"- **Name:** {c.name}\n"
            md_content += f"- **Role:** {c.role or 'Decision Maker'}\n"
            md_content += f"- **Apollo Verified Email:** `{c.email or 'N/A'}`\n"
            md_content += f"- **Rationale:** {report.recommended_contact_reason}\n\n"

        md_content += "## Detailed Strategic Analysis\n\n"
        if sections:
            for sec in sections:
                title = getattr(sec, "heading", None) or getattr(sec, "theme_title", "Analysis Section")
                md_content += f"### {title}\n\n{sec.paragraph}\n\n"
        else:
            for theme, findings in report.findings_by_theme.items():
                md_content += f"### {theme}\n\n"
                md_content += " ".join(findings) + "\n\n"

        if report.contacts:
            md_content += "## Discovered Key Contacts\n\n"
            for c in report.contacts:
                md_content += f"- **{c.name}** ({c.role or 'Executive'}) — Email: `{c.email or 'N/A'}`\n"
            md_content += "\n"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(md_content)

        path_str = os.path.abspath(filename)
        print(f"[Synthesizer] Saved clean prose research report to disk: {path_str}")
        return path_str
    except Exception as e:
        print(f"[Synthesizer Warning] Failed to save report to disk: {e}")
        return ""


def synthesizer_node(state: State) -> dict:
    reranked = state.reranked or []
    contacts = state.verified_contacts or []
    query = state.query or "Research Query"
    goal = state.goal

    # Deduplicate findings & contacts before synthesis
    unique_reranked = _deduplicate_findings(reranked)
    unique_contacts = _deduplicate_contacts(contacts)

    if not unique_reranked:
        empty_report = Report(
            summary="No verified findings were available for this request.",
            findings_by_theme={},
            contacts=unique_contacts,
            citations=[],
            recommended_contact=unique_contacts[0] if unique_contacts else None,
            recommended_contact_reason="First contact selected by default." if unique_contacts else "No contacts available.",
        )
        filepath = _save_report_to_disk(empty_report, query, [])
        return {"report": empty_report, "report_filepath": filepath}

    raw = mid_llm.generate(
        prompt=f"""Write an executive research brief based on the verified findings below.

        RULES:
        1. Write in structured prose paragraphs with clear subheadings — not bullet lists.
        2. Each fact should appear exactly once across the entire brief. Before writing a claim, check whether you've already covered it under a different heading.
        3. Organize findings into thematic sections, grouped by subject (e.g. "Market Position", "Technical Stack", "Hiring Signals") — not by which researcher found them.
        4. When picking recommended_contact_name, prefer whoever has the most seniority/decision-making authority for the stated goal and an actual email on file over one without; state that reasoning in recommended_contact_reason. If no contact stands out, leave recommended_contact_name blank rather than guessing.

        Original Request: "{query}"
        Goal: "{goal or 'general'}"

        Verified Research Findings:
        {_format_findings(unique_reranked)}

        Contacts Available:
        {_format_contacts(unique_contacts)}
        """,
        response_model=SynthesizerOutput,
    )


    findings_by_theme = {sec.heading: [sec.paragraph] for sec in raw.sections}

    rec_contact = None
    if raw.recommended_contact_name and unique_contacts:
        for c in unique_contacts:
            if c.name and raw.recommended_contact_name.lower() in c.name.lower():
                rec_contact = c
                break
    if not rec_contact and unique_contacts:
        rec_contact = unique_contacts[0]

    report = Report(
        summary=raw.executive_summary,
        findings_by_theme=findings_by_theme,
        contacts=unique_contacts,
        citations=unique_reranked,
        recommended_contact=rec_contact,
        recommended_contact_reason=raw.recommended_contact_reason if rec_contact else None,
    )

    filepath = _save_report_to_disk(report, query, raw.sections)

    return {"report": report, "report_filepath": filepath}


def _format_findings(findings) -> str:
    return "\n".join(f"{idx}. {f.claim}" for idx, f in enumerate(findings, 1))


def _format_contacts(contacts) -> str:
    if not contacts:
        return "(none found)"
    return "\n".join(f"- {c.name} ({c.role or 'Executive'}) — Email: {c.email or 'N/A'}" for c in contacts)