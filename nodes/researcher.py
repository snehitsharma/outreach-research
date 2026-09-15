

from config import config
from schemas import Finding, Contact, Confidence
from llm_clients import light_llm
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
    company: str = Field(default="", description="Company this person works at, based on the source content")
    snippet: str = Field(default="", description="Context snippet from search/page")
    confidence: str = Field(default="medium", description="high, medium, or low")


class ExtractedItems(BaseModel):
    findings: list[ExtractedFinding] = Field(default_factory=list)
    contacts: list[ExtractedContact] = Field(default_factory=list)

def _parse_confidence(val: str | None) -> Confidence:
    if not val:
        return Confidence.MEDIUM
    val_lower = str(val).lower()
    if "high" in val_lower:
        return Confidence.HIGH
    if "low" in val_lower:
        return Confidence.LOW
    return Confidence.MEDIUM

def _format_history(history: list[dict]) -> str:
    if not history:
        return "(no actions taken yet)"
    lines = []
    for h in history:
        res = str(h.get("result", ""))[:200]
        lines.append(f"- Action: {h['action']}, Input: {h['input']} -> Result preview: {res}")
    return "\n".join(lines)


def researcher_node(input: dict) -> dict:
    
    angle = input["angle"]
    query = input["query"]
    goal = input.get("goal")
    researcher_id = f"r_{uuid.uuid4().hex[:6]}"

    history = []
    action_count = 0
    new_findings = []
    new_contacts = []

    while action_count < config.MAX_ACTIONS:
        try:
            decision = light_llm.generate(
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
        except Exception:
            break

        if decision.action == "stop":
            break

        content_to_extract = ""
        source_link = decision.query_or_url or ""

        try:
            if decision.action == "search" and decision.query_or_url:
                search_results = search_tool.run(decision.query_or_url)
                history.append({"action": "search", "input": decision.query_or_url, "result": search_results})

                if search_results and isinstance(search_results, list):
                    snippets = [
                        f"Title: {r.get('title')}\nURL: {r.get('url')}\nSnippet: {r.get('snippet')}"
                        for r in search_results if isinstance(r, dict)
                    ]
                    content_to_extract = "\n\n".join(snippets)
                    source_link = search_results[0].get("url", source_link) if search_results else source_link

            elif decision.action == "scrape" and decision.query_or_url:
                scraped_text = scrape_tool.run(decision.query_or_url)
                history.append({"action": "scrape", "input": decision.query_or_url, "result": scraped_text})
                content_to_extract = str(scraped_text)[:3500]
        except Exception:
            action_count += 1
            continue

        if content_to_extract:
            extracted = light_llm.generate(
                prompt=f"""Extract key research findings and decision-maker names/roles from this text.

                Angle: "{angle}" | Goal: "{goal or 'general'}"
                Source Link: {source_link}

                Content:
                {content_to_extract}
                """,
                response_model=ExtractedItems,
            )

            
            for item in extracted.findings:
                if item.claim:
                    new_findings.append(
                        Finding(
                            researcher_id=researcher_id,
                            src_link=source_link,
                            snippet=item.snippet,
                            confidence=_parse_confidence(item.confidence),
                            claim=item.claim,
                        )
                    )

            for item in extracted.contacts:
               
                if item.name:
                    new_contacts.append(
                        Contact(
                            researcher_id=researcher_id,
                            src_link=source_link,
                            snippet=item.snippet,
                            confidence=_parse_confidence(item.confidence),
                            name=item.name,
                            role=item.role,
                            company=item.company,
                            email=None,
                            phone=None,
                        )
                    )

        action_count += 1

    return {"findings": new_findings, "contacts": new_contacts}

