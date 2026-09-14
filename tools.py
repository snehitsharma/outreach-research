import os

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


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
    def run(query: str) -> list[dict]:
        client = _get_tavily_client()
        if not client:
            return [{
                "title": f"Result for {query}",
                "url": "https://example.com",
                "snippet": f"Snippet about {query}",
            }]

        try:
            response = client.search(query=query, max_results=5)
            return [
                {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("content", ""),
                }
                for result in response.get("results", [])
            ]
        except Exception as error:
            return [{"title": "", "url": "", "snippet": f"Search failed: {error}"}]


class scrape_tool:
    @staticmethod
    def run(url: str) -> str:
        client = _get_tavily_client()
        if client:
            try:
                response = client.extract(urls=[url])
                results = response.get("results", [])
                if results and results[0].get("raw_content"):
                    return results[0]["raw_content"][:4000]
            except Exception:
                pass

        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.decompose()

            return soup.get_text(separator=" ", strip=True)[:4000]
        except Exception as error:
            return f"Scrape failed: {error}"


class apollo_tool:
    @staticmethod
    def run(name: str, company: str = "Google") -> dict:
        key = os.environ.get("APOLLO_API_KEY", "")
        if key and not key.startswith("apollo_dev") and not key.startswith("your_"):
            try:
                parts = name.strip().split()
                first = parts[0] if parts else name
                last = parts[-1] if len(parts) > 1 else ""
                response = requests.post(
                    "https://api.apollo.io/v1/people/match",
                    headers={
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache",
                    },
                    json={
                        "api_key": key,
                        "first_name": first,
                        "last_name": last,
                        "organization_name": company,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code == 200:
                    person = response.json().get("person") or {}
                    email = person.get("email")
                    if email:
                        return {
                            "email": email,
                            "title": person.get("title") or "Executive / Manager",
                            "source": "apollo_api",
                        }
            except Exception:
                pass

        return {
            "email": "N/A",
            "title": f"Executive / Manager at {company}",
            "source": "apollo_unverified",
        }


class cross_encoder:
    @staticmethod
    def score(query: str, documents: list[str]) -> list[float]:
        try:
            from sentence_transformers import CrossEncoder
            model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            pairs = [[query, document] for document in documents]
            scores = model.predict(pairs)
            return [float(score) for score in scores]
        except Exception as error:
            print(f"[CrossEncoder Warning] Fallback scoring due to: {error}")
            return [1.0] * len(documents)
