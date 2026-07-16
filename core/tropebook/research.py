"""
Research Tool - Web search and scraping for Tropebook
Supports Brave Search API and free alternatives.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests

try:
    from duckduckgo_search import DDGS  # noqa: F401
    DUCKDUCKGO_AVAILABLE = True
except ImportError:
    DUCKDUCKGO_AVAILABLE = False

@dataclass
class SearchResult:
    title: str
    url: str
    description: str = ""
    source: str = "web"

@dataclass
class ScrapedContent:
    url: str
    title: str
    content: str
    excerpt: str = ""
    links: list[str] = field(default_factory=list)

class BraveSearch:
    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, rate_limit: float = 1.0):
        self.api_key = api_key
        self.rate_limit = rate_limit
        self.last_request = 0

    def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        if not self.api_key:
            return self._free_search_fallback(query, num_results)

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
            "User-Agent": "Tropebook/1.0"
        }
        params = {
            "q": query,
            "count": min(num_results, 20),
            "safesearch": "moderate"
        }

        while time.time() - self.last_request < self.rate_limit:
            time.sleep(0.1)

        try:
            resp = requests.get(self.BASE_URL, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("web", {}).get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    description=item.get("description", ""),
                    source="brave"
                ))
            return results
        except Exception as e:
            print(f"Brave API error: {e}")
            return self._free_search_fallback(query, num_results)

    def _free_search_fallback(self, query: str, num_results: int) -> list[SearchResult]:
        results = []
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=num_results):
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        description=r.get("body", ""),
                        source="duckduckgo"
                    ))
        except ImportError:
            pass
        return results

class WebScraper:
    def __init__(self, user_agent: str = "Tropebook/1.0 (research tool)"):
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def scrape(self, url: str, extract_links: bool = True) -> ScrapedContent | None:
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None

            html = resp.text
            title = self._extract_title(html)
            text = self._extract_text(html)
            excerpt = text[:500] if len(text) > 500 else text
            links = self._extract_links(html) if extract_links else []

            return ScrapedContent(
                url=url,
                title=title,
                content=text,
                excerpt=excerpt,
                links=links
            )
        except Exception as e:
            print(f"Scraping error for {url}: {e}")
            return None

    def _extract_title(self, html: str) -> str:
        match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _extract_text(self, html: str) -> str:
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-z]+;', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _extract_links(self, html: str) -> list[str]:
        pattern = r'href=["\'](https?://[^"\']+)["\']'
        return list(set(re.findall(pattern, html, re.IGNORECASE)))[:50]

class ResearchTool:
    def __init__(self, brave_api_key: str | None = None, storage_path: str = "memory/tropebook/"):
        self.search = BraveSearch(api_key=brave_api_key)
        self.scraper = WebScraper()
        self.tropebook = None

        try:
            from .ropebook import Tropebook
            self.tropebook = Tropebook(storage_path)
        except (ImportError, Exception):
            pass

    def research(self, query: str, num_results: int = 10, scrape: bool = True,
                add_to_tropebook: bool = True) -> list[SearchResult]:
        results = self.search.search(query, num_results)

        if add_to_tropebook and self.tropebook and scrape:
            for result in results:
                content = self.scraper.scrape(result.url, extract_links=True)
                if content:
                    entities = self._extract_entities(content.content)
                    tags = self._extract_tags(content.content, query)
                    self.tropebook.add(
                        title=result.title,
                        url=result.url,
                        summary=content.excerpt,
                        source=result.source,
                        tags=tags,
                        entities=entities,
                        source_type="brave_search" if result.source == "brave" else "web"
                    )
                    if content.links:
                        for link in content.links[:5]:
                            scraped_link = self.scraper.scrape(link)
                            link_title = scraped_link.title if scraped_link else link
                            self.tropebook.add(
                                title=link_title,
                                url=link,
                                source="scraped"
                            )

        return results

    def research_and_scrape(self, query: str, num_results: int = 10) -> list[ScrapedContent]:
        results = self.search.search(query, num_results)
        scraped = []
        for result in results:
            content = self.scraper.scrape(result.url)
            if content:
                scraped.append(content)
        return scraped

    def _extract_entities(self, text: str, max_entities: int = 10) -> list[str]:
        entities = []
        patterns = [
            r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b',
            r'\b(?:AI|ML|LLM|GPT|NLP|CV|CNN|RAG)\b',
            r'\b(?:Python|JavaScript|TypeScript|Rust|Go|C\+\+)\b',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            entities.extend(matches[:max_entities])
        return list(set(entities))[:max_entities]

    def _extract_tags(self, text: str, query: str) -> list[str]:
        tags = [query]
        common_tags = ["tutorial", "guide", "documentation", "api", "framework",
                       "tool", "library", "paper", "blog", "research", "code"]
        for tag in common_tags:
            if tag in text.lower():
                tags.append(tag)
        return list(set(tags))[:10]

    def extend_from_source(self, source_data: dict, source_type: str = "deep_research"):
        if not self.tropebook:
            return 0

        if source_type == "deep_research":
            return self.tropebook.import_from_deep_research(source_data)

        return 0

def create_researcher(api_key: str | None = None) -> ResearchTool:
    return ResearchTool(brave_api_key=api_key)
