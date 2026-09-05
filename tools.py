# ============================================================
# tools.py — Web Search, Scraping & Apollo Tools with Telemetry Tracing
# ============================================================

import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from events import events_manager

load_dotenv()

USER_AGENT = "Mozilla/5.0 (research-agent/1.0)"
REQUEST_TIMEOUT = 10


def _get_tavily_client():
    key = os.environ.get("TAVILY_API_KEY", "")
    if key and not key.startswith("your_"):
        try:
            from tavily import TavilyClient
            return TavilyClient(api_key=key)
        except Exception:
            return None
    return None


class search_tool:
    @staticmethod
    def run(query: str, job_id: str | None = None) -> list[dict]:
        """Returns a list of {title, url, snippet} search results with live event logging."""
        if job_id:
            events_manager.emit(
                job_id=job_id,
                node="researcher",
                event_type="api_call",
                message=f"Executing Tavily Web Search API for query: '{query}'",
                payload={"tool": "tavily_search", "query": query},
            )

        client = _get_tavily_client()
        if not client:
            if job_id:
                events_manager.emit(
                    job_id=job_id,
                    node="researcher",
                    event_type="warning",
                    message="Tavily API Key missing or fallback active; using stubbed search results.",
                    payload={"tool": "tavily_search", "status": "no_api_key"},
                )
            return [{"title": f"Result for {query}", "url": "https://example.com", "snippet": f"Snippet about {query}"}]

        try:
            response = client.search(query=query, max_results=5)
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in response.get("results", [])
            ]

            if job_id:
                events_manager.emit(
                    job_id=job_id,
                    node="researcher",
                    event_type="tool_result",
                    message=f"Search retrieved {len(results)} web results for: '{query}'",
                    payload={"query": query, "count": len(results), "urls": [r["url"] for r in results[:3]]},
                )
            return results
        except Exception as e:
            if job_id:
                events_manager.emit(
                    job_id=job_id,
                    node="researcher",
                    event_type="error",
                    message=f"Tavily search API failed for query '{query}': {e}",
                    payload={"error": str(e)},
                )
            return [{"title": "", "url": "", "snippet": f"Search failed: {e}"}]


class scrape_tool:
    @staticmethod
    def run(url: str, job_id: str | None = None) -> str:
        """
        Scrapes web page content with live telemetry tracing. Uses Tavily Extract if API key is available,
        falling back to requests + BeautifulSoup.
        """
        if job_id:
            events_manager.emit(
                job_id=job_id,
                node="researcher",
                event_type="api_call",
                message=f"Scraping web page URL: '{url}'",
                payload={"tool": "web_scraper", "url": url},
            )

        client = _get_tavily_client()
        if client:
            try:
                res = client.extract(urls=[url])
                results = res.get("results", [])
                if results and results[0].get("raw_content"):
                    raw = results[0]["raw_content"][:4000]
                    if job_id:
                        events_manager.emit(
                            job_id=job_id,
                            node="researcher",
                            event_type="tool_result",
                            message=f"Tavily Extract successfully scraped {len(raw)} characters from {url}",
                            payload={"url": url, "chars": len(raw)},
                        )
                    return raw
            except Exception as e:
                if job_id:
                    events_manager.emit(
                        job_id=job_id,
                        node="researcher",
                        event_type="warning",
                        message=f"Tavily Extract fallback to standard scraper for {url}: {e}",
                    )

        # Fallback: standard requests + BeautifulSoup
        headers = {"User-Agent": USER_AGENT}
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for el in soup(["script", "style", "nav", "footer", "header", "aside"]):
                el.decompose()

            text = soup.get_text(separator=" ", strip=True)[:4000]
            if job_id:
                events_manager.emit(
                    job_id=job_id,
                    node="researcher",
                    event_type="tool_result",
                    message=f"Standard web scraper retrieved {len(text)} characters from {url}",
                    payload={"url": url, "chars": len(text)},
                )
            return text
        except Exception as e:
            if job_id:
                events_manager.emit(
                    job_id=job_id,
                    node="researcher",
                    event_type="error",
                    message=f"Scrape failed for {url}: {e}",
                )
            return f"Scrape failed: {e}"


class apollo_tool:
    @staticmethod
    def run(name: str, company: str = "Google", job_id: str | None = None) -> dict:
        """
        Queries Apollo API (/v1/people/match or /v1/people/search) to discover verified contact email and title.
        Returns 'N/A' for email if not found in Apollo API (no unverified pattern generation).
        """
        if job_id:
            events_manager.emit(
                job_id=job_id,
                node="verifier",
                event_type="api_call",
                message=f"Executing Apollo Contact Search API for '{name}' at '{company}'",
                payload={"tool": "apollo_search", "name": name, "company": company},
            )

        key = os.environ.get("APOLLO_API_KEY", "")
        if key and not key.startswith("apollo_dev") and not key.startswith("your_"):
            try:
                parts = name.strip().split()
                first = parts[0] if parts else name
                last = parts[-1] if len(parts) > 1 else ""
                resp = requests.post(
                    "https://api.apollo.io/v1/people/match",
                    headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
                    json={"api_key": key, "first_name": first, "last_name": last, "organization_name": company},
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    person = resp.json().get("person") or {}
                    email = person.get("email")
                    title = person.get("title")
                    if email:
                        if job_id:
                            events_manager.emit(
                                job_id=job_id,
                                node="verifier",
                                event_type="tool_result",
                                message=f"Apollo API found verified email for {name}: {email}",
                                payload={"name": name, "email": email, "title": title},
                            )
                        return {"email": email, "title": title or "Executive / Manager", "source": "apollo_api"}
            except Exception as e:
                if job_id:
                    events_manager.emit(
                        job_id=job_id,
                        node="verifier",
                        event_type="warning",
                        message=f"Apollo API lookup exception for {name}: {e}",
                    )

        # Strictly return N/A for unverified emails (no pattern fallbacks)
        if job_id:
            events_manager.emit(
                job_id=job_id,
                node="verifier",
                event_type="tool_result",
                message=f"Apollo API lookup for {name}: No verified email found (set to N/A)",
                payload={"name": name, "email": "N/A", "source": "apollo_unverified"},
            )

        return {"email": "N/A", "title": f"Executive / Manager at {company}", "source": "apollo_unverified"}


class cross_encoder:
    @staticmethod
    def score(query: str, documents: list[str]) -> list[float]:
        """Scores candidate document relevance against query using sentence-transformers CrossEncoder."""
        try:
            from sentence_transformers import CrossEncoder
            model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            pairs = [[query, doc] for doc in documents]
            scores = model.predict(pairs)
            return [float(s) for s in scores]
        except Exception as e:
            print(f"[CrossEncoder Warning] Fallback scoring due to: {e}")
            return [1.0] * len(documents)