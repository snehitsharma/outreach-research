# ============================================================
# nodes/researcher.py — Telemetry Instrumented & Resilient Parser
# ============================================================

from config import config
from schemas import Finding, Contact, Confidence
from llm_clients import cheap_llm
from tools import search_tool, scrape_tool
from pydantic import BaseModel, Field
from typing import Literal, Any
import uuid


class ResearcherDecision(BaseModel):
    action: Literal["search", "scrape", "stop"] = "stop"
    query_or_url: str | None = Field(default=None, description="search query, or URL to scrape")
    reasoning: str = Field(default="", description="short justification")


class ExtractedFinding(BaseModel):
    claim: str = Field(default="", description="Key fact or requirement discovered on the page")
    snippet: str = Field(default="", description="Direct quote or snippet from page")
    confidence: str = Field(default="medium", description="high, medium, or low")


class ExtractedContact(BaseModel):
    name: str = Field(default="", description="Full name of key decision maker, manager, or executive")
    role: str = Field(default="", description="Role or title, e.g. VP of Engineering or Head of Sales")
    snippet: str = Field(default="", description="Context snippet from search/page")
    confidence: str = Field(default="medium", description="high, medium, or low")


class ExtractedItems(BaseModel):
    findings: list[Any] = Field(default_factory=list)
    contacts: list[Any] = Field(default_factory=list)


def researcher_node(input: dict) -> dict:
    """
    Runs for one angle. Called N times in parallel via Send().
    input = {"angle": str, "query": str, "goal": str | None, "job_id": str | None}
    """
    angle = input["angle"]
    query = input["query"]
    goal = input.get("goal")
    job_id = input.get("job_id")
    researcher_id = f"r_{uuid.uuid4().hex[:6]}"

    history = []
    action_count = 0
    new_findings = []
    new_contacts = []

    while action_count < config.MAX_ACTIONS:
        decision = cheap_llm.generate(
            prompt=f"""You are researching: "{query}" (overall goal: {goal or 'general'}).
            Your specific angle: "{angle}"

            History so far:
            {_format_history(history)}

            Decide your next action:
            - "search": run a web search with a specific query
            - "scrape": fetch a specific URL from prior search results
            - "stop": you have enough information for this angle

            Budget remaining: {config.MAX_ACTIONS - action_count} actions.
            """,
            response_model=ResearcherDecision,
        )

        act = getattr(decision, "action", None) or "stop"
        query_or_url = getattr(decision, "query_or_url", None) or ""

        if act == "stop":
            break

        content_to_extract = ""
        source_link = query_or_url

        if act == "search" and query_or_url:
            search_results = search_tool.run(query_or_url)
            history.append({"action": "search", "input": query_or_url, "result": search_results})

            if search_results and isinstance(search_results, list):
                snippets = [f"Title: {r.get('title')}\nURL: {r.get('url')}\nSnippet: {r.get('snippet')}" for r in search_results if isinstance(r, dict)]
                content_to_extract = "\n\n".join(snippets)
                source_link = search_results[0].get("url", query_or_url) if search_results else query_or_url

        elif act == "scrape" and query_or_url:
            scraped_text = scrape_tool.run(query_or_url)
            history.append({"action": "scrape", "input": query_or_url, "result": scraped_text})
            content_to_extract = str(scraped_text)[:3500]
            source_link = query_or_url

        if content_to_extract:
            extracted = cheap_llm.generate(
                prompt=f"""Extract key research findings and decision-maker names/roles from this text.
                Do NOT extract emails or phone numbers from web search (email resolution is handled downstream via Apollo API enrichment).

                Angle: "{angle}" | Goal: "{goal or 'general'}"
                Source Link: {source_link}

                Content:
                {content_to_extract}
                """,
                response_model=ExtractedItems,
            )

            raw_findings = getattr(extracted, "findings", []) or []
            raw_contacts = getattr(extracted, "contacts", []) or []

            for item in raw_findings:
                claim, snippet, conf = _parse_finding_item(item)
                if claim:
                    new_findings.append(
                        Finding(
                            researcher_id=researcher_id,
                            src_link=source_link,
                            snippet=snippet,
                            confidence=_parse_confidence(conf),
                            claim=claim,
                        )
                    )

            for item in raw_contacts:
                name, role, snippet, conf = _parse_contact_item(item)
                if name:
                    new_contacts.append(
                        Contact(
                            researcher_id=researcher_id,
                            src_link=source_link,
                            snippet=snippet,
                            confidence=_parse_confidence(conf),
                            name=name,
                            role=role,
                            email=None,
                            phone=None,
                        )
                    )

        action_count += 1

    return {"findings": new_findings, "contacts": new_contacts}


def _parse_finding_item(item: Any) -> tuple[str, str, str]:
    if isinstance(item, str):
        return item.strip(), "", "medium"
    if isinstance(item, dict):
        claim = item.get("claim") or item.get("finding") or item.get("statement") or item.get("text") or str(item)
        snippet = item.get("snippet", "")
        conf = item.get("confidence", "medium")
        return str(claim).strip(), str(snippet), str(conf)
    claim = getattr(item, "claim", None) or getattr(item, "finding", str(item))
    snippet = getattr(item, "snippet", "")
    conf = getattr(item, "confidence", "medium")
    return str(claim).strip(), str(snippet), str(conf)


def _parse_contact_item(item: Any) -> tuple[str, str | None, str, str]:
    if isinstance(item, str):
        return item.strip(), None, "", "medium"
    if isinstance(item, dict):
        name = item.get("name") or item.get("person") or item.get("contact")
        if not name:
            return "", None, "", "medium"
        return (
            str(name).strip(),
            item.get("role"),
            str(item.get("snippet", "")),
            str(item.get("confidence", "medium")),
        )
    name = getattr(item, "name", "")
    if not name:
        return "", None, "", "medium"
    return (
        str(name).strip(),
        getattr(item, "role", None),
        str(getattr(item, "snippet", "")),
        str(getattr(item, "confidence", "medium")),
    )


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(no actions taken yet)"
    lines = []
    for h in history:
        res = str(h.get("result", ""))[:200]
        lines.append(f"- Action: {h['action']}, Input: {h['input']} -> Result preview: {res}")
    return "\n".join(lines)


def _parse_confidence(val: str | None) -> Confidence:
    if not val:
        return Confidence.MEDIUM
    val_lower = str(val).lower()
    if "high" in val_lower:
        return Confidence.HIGH
    if "low" in val_lower:
        return Confidence.LOW
    return Confidence.MEDIUM