"""
Tropebook Adapter for Tropelex
Integrates Tropebook research capabilities with Tropelex memory system.
"""
from typing import Any


class TropebookAdapter:
    def __init__(self, storage_path: str = "memory/tropebook/"):
        self.storage_path = storage_path
        self.tropebook = None
        self.researcher = None
        self._init_components()

    def _init_components(self):
        try:
            from core.tropebook import Tropebook, create_researcher
            self.tropebook = Tropebook(self.storage_path)
            self.researcher = create_researcher()
        except ImportError as e:
            print(f"Tropebook components not available: {e}")

    def research(self, query: str, num_results: int = 10) -> list[Any]:
        if not self.researcher:
            return []
        return self.researcher.research(query, num_results)

    def add_citation(self, title: str, url: str, summary: str = "",
                    tags: list[str] = None, entities: list[str] = None) -> str | None:
        if not self.tropebook:
            return None
        return self.tropebook.add(title, url, summary, tags=tags, entities=entities)

    def search_knowledge(self, query: str, limit: int = 20) -> list[Any]:
        if not self.tropebook:
            return []
        return self.tropebook.search(query, limit)

    def import_deep_research(self, data: dict) -> int:
        if not self.tropebook:
            return 0
        return self.tropebook.import_from_deep_research(data)

    def get_related(self, url: str, depth: int = 1) -> dict[str, Any]:
        if not self.tropebook:
            return {}
        cite = self.tropebook.find_by_url(url)
        if not cite:
            return {}
        cid = self.tropebook._index["by_url"].get(url)
        if not cid:
            return {}
        return self.tropebook.get_related(cid, depth)

    def link_citations(self, url1: str, url2: str, relationship: str):
        if not self.tropebook:
            return
        self.tropebook.add_relationship(url1, url2, relationship)

    def extend_research(self, source_data: dict, source_type: str = "deep_research") -> int:
        if not self.researcher:
            return 0
        return self.researcher.extend_from_source(source_data, source_type)

    def get_stats(self) -> dict[str, Any]:
        if not self.tropebook:
            return {}
        return self.tropebook.stats()

    def export_knowledge(self) -> dict:
        if not self.tropebook:
            return {}
        return self.tropebook.export_json()

def create_tropebook_adapter(storage_path: str = "memory/tropebook/") -> TropebookAdapter:
    return TropebookAdapter(storage_path)
