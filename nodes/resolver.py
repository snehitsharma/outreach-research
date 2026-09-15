

from state import State
from schemas import Penalty, ResolverDecision, Contact
from llm_clients import three_tier_llm
from tools import scrape_tool, search_tool
from pydantic import BaseModel, Field
from typing import Literal
from config import config


class ResolverVerdict(BaseModel):
    decision: Literal["keep", "discard", "reprioritize"] = "discard"
    reasoning: str = ""


class ContactsExtraction(BaseModel):
    contacts: list[Contact] = Field(default_factory=list)


def resolver_node(state: State) -> dict:

    penalties = state.penalties or []
    next_retry_count = state.retry_count + 1

    if not penalties:
        contacts = state.contacts or []
        if not _contacts_valid(contacts):
            found = _extract_contacts_from_findings(state) or _search_and_scrape_contacts(state)
            return {"resolved_penalties": [], "contacts": found, "retry_count": next_retry_count}
        return {"resolved_penalties": [], "retry_count": next_retry_count}

    priority_order = {"missing_expected": 0, "contradicted": 1, "unsupported": 2, "low_relevance": 3}
    ranked = sorted(penalties, key=lambda p: priority_order.get(p.rejection_reason.value, 99))
    to_resolve = ranked[: config.MAX_PENALTIES_TO_RESOLVE]
    skipped = ranked[config.MAX_PENALTIES_TO_RESOLVE :]

    resolved = [_resolve_one(penalty, state) for penalty in to_resolve]

    # Anything past the cap gets auto-discarded — no budget left to investigate
    for penalty in skipped:
        penalty.resolver_decision = ResolverDecision.DISCARD
        resolved.append(penalty)

    contacts = state.contacts or []
    if not _contacts_valid(contacts):
        found = _extract_contacts_from_findings(state) or _search_and_scrape_contacts(state)
        return {"resolved_penalties": resolved, "contacts": found, "retry_count": next_retry_count}

    return {"resolved_penalties": resolved, "retry_count": next_retry_count}



def _resolve_one(penalty: Penalty, state: State) -> Penalty:
    # Coverage-gap penalties have no src_link to re-check — just re-scan
    # existing pooled findings for anything that was miscategorized
    if getattr(penalty.rejection_reason, "value", "") == "missing_expected" and not penalty.src_link:
        verdict = three_tier_llm.generate(
            prompt=f"""We expected to find a contact but didn't. Re-check these
            findings, did any researcher surface a name/role/contact info that
            wasn't properly extracted as a contact?

            Gap description: {penalty.claim}
            Findings: {[f.claim for f in getattr(state, 'findings', [])]}
            """,
            response_model=ResolverVerdict,
        )
        dec_val = getattr(verdict, "decision", "discard") or "discard"
        if dec_val != "discard":
            penalty.resolver_decision = ResolverDecision(dec_val)
            return penalty

    # Otherwise: re-check against the source directly, with a small fresh-look budget
    content = None
    if getattr(penalty, "src_link", None):
        try:
            content = scrape_tool.run(penalty.src_link)
        except Exception:
            content = None

    verdict = three_tier_llm.generate(
        prompt=f"""Re-investigate this flagged claim using the source content below.
        Original rejection reason: {getattr(penalty.rejection_reason, 'value', None)}

        Claim: {penalty.claim}
        Original snippet: {penalty.snippet}
        Source content (fresh fetch): {(content or 'fetch failed')[:4000]}

        Decide: keep (claim holds up), discard (claim is wrong/irrelevant/unfixable),
        or reprioritize (claim is valid but should be weighted differently, e.g.
        downgraded from a headline finding to a minor detail).
        """,
        response_model=ResolverVerdict,
    )

    dec_val = getattr(verdict, "decision", "discard") or "discard"
    try:
        penalty.resolver_decision = ResolverDecision(dec_val)
    except Exception:
        penalty.resolver_decision = ResolverDecision.DISCARD

    return penalty


def _contacts_valid(contacts: list[Contact]) -> bool:
    """Check for a minimally valid contacts list: at least one contact with a
    name and an email or phone number."""
    if not contacts:
        return False
    for c in contacts:
        if getattr(c, "name", None) and (getattr(c, "email", None) or getattr(c, "phone", None)):
            return True
    return False


def _extract_contacts_from_findings(state: State) -> list[Contact]:
    """Scan accumulated findings text for contact info that was captured as findings rather than contacts."""
    findings = getattr(state, "findings", []) or []
    if not findings:
        return []
    claims_text = "\n".join(f"- {f.claim} ({f.snippet})" for f in findings)
    extracted = three_tier_llm.generate(
        prompt=f"Extract any contact details (name, role, email, phone) embedded in these research findings:\n{claims_text}",
        response_model=ContactsExtraction,
    )
    return getattr(extracted, "contacts", []) or []


def _search_and_scrape_contacts(state: State) -> list[Contact]:
    """Fallback search pass specifically targeted at discovering contact emails for the target entity."""
    query = state.query or state.raw_query
    results = search_tool.run(f"{query} contact email decision maker")
    extracted = three_tier_llm.generate(
        prompt=f"Extract key contacts (name, role, email) from these search results for query '{query}':\n{results[:3000]}",
        response_model=ContactsExtraction,
    )
    return getattr(extracted, "contacts", []) or []