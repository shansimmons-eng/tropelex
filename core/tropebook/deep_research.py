"""
Deep Research Importer for Tropebook
Parses and imports Google Deep Research outputs, NotebookLM exports, and similar formats.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.tropebook.tropebook import SourceType


@dataclass
class DeepResearchSource:
    title: str
    url: str
    snippet: str = ""
    domain: str = ""
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    credibility_score: float = 0.0

class DeepResearchImporter:
    def __init__(self, tropebook_instance=None):
        self.tropebook = tropebook_instance

    def parse_notebooklm_export(self, file_path: str) -> list[DeepResearchSource]:
        sources = []
        try:
            with open(file_path, encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, dict):
                if "sources" in data:
                    data = data["sources"]
                elif "citations" in data:
                    data = data["citations"]

            for item in data:
                if isinstance(item, dict):
                    source = DeepResearchSource(
                        title=item.get("title", item.get("name", "Unknown")),
                        url=item.get("url", item.get("link", "")),
                        snippet=item.get("snippet", item.get("summary", "")),
                        domain=self._extract_domain(item.get("url", "")),
                        topics=item.get("topics", item.get("tags", [])),
                        entities=item.get("entities", [])
                    )
                    if source.url:
                        sources.append(source)
        except Exception as e:
            print(f"Error parsing NotebookLM export: {e}")
        return sources

    def parse_google_deep_research(self, text: str) -> list[DeepResearchSource]:
        sources = []
        lines = text.split('\n')
        current_source = None

        for line in lines:
            url_match = re.search(r'https?://[^\s\)\]"\'>]+', line)
            if url_match:
                if current_source and current_source.url:
                    sources.append(current_source)
                current_source = DeepResearchSource(
                    url=url_match.group(0),
                    title=line[:url_match.start()].strip(),
                    domain=self._extract_domain(url_match.group(0))
                )
            elif current_source and not current_source.snippet:
                current_source.snippet = line.strip()

        if current_source and current_source.url:
            sources.append(current_source)

        return sources

    def parse_markdown_research(self, text: str) -> list[DeepResearchSource]:
        sources = []
        pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
        matches = re.findall(pattern, text)

        for title, url in matches:
            domain = self._extract_domain(url)
            source = DeepResearchSource(
                title=title.strip(),
                url=url.strip(),
                domain=domain
            )
            sources.append(source)

        return sources

    def import_sources(self, sources: list[DeepResearchSource],
                      add_relationships: bool = True,
                      source_type: SourceType = SourceType.GOOGLE_DEEP_RESEARCH) -> int:
        if not self.tropebook:
            return 0

        count = 0
        for source in sources:
            if not source.url:
                continue

            self.tropebook.add(
                title=source.title,
                url=source.url,
                summary=source.snippet,
                tags=source.topics or [],
                entities=source.entities or [],
                source_type=source_type
            )
            count += 1

        if add_relationships and len(sources) > 1:
            for i in range(len(sources) - 1):
                self.tropebook.add_relationship(
                    sources[i].url,
                    sources[i + 1].url,
                    "related_to"
                )

        return count

    def import_file(self, file_path: str) -> int:
        if not self.tropebook:
            return 0

        suffix = Path(file_path).suffix.lower()
        if suffix == '.json':
            parsed = self.parse_notebooklm_export(file_path)
        elif suffix == '.md':
            with open(file_path, encoding='utf-8') as f:
                content = f.read()
            parsed = self.parse_markdown_research(content)
        else:
            with open(file_path, encoding='utf-8') as f:
                content = f.read()
            parsed = self.parse_google_deep_research(content)

        return self.import_sources(parsed)

    def _extract_domain(self, url: str) -> str:
        match = re.search(r'https?://([^/]+)', url)
        return match.group(1) if match else ""

def create_importer(tropebook_instance=None) -> DeepResearchImporter:
    return DeepResearchImporter(tropebook_instance)
