"""
Tropebook - Research Knowledge Base
Stores links, summaries, and relationships for building extended knowledge graphs.
"""

import json
import uuid
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Set, Any, Union
from pathlib import Path
from enum import Enum


class SourceType(Enum):
    BRAVE_SEARCH = "brave_search"
    GOOGLE_DEEP_RESEARCH = "google_deep_research"
    MANUAL = "manual"
    SCRAPED = "scraped"
    IMPORTED = "imported"


@dataclass
class Citation:
    title: str
    url: str
    summary: str = ""
    source: str = ""
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_accessed: str = ""
    access_count: int = 0
    source_type: str = SourceType.MANUAL.value
    metadata: Dict = field(default_factory=dict)

    def to_dict(self, id: str = None) -> dict:
        d = asdict(self)
        if id:
            d["id"] = id
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Citation":
        data.pop("id", None)
        return cls(**data)


@dataclass
class KnowledgeGraph:
    nodes: Dict[str, dict] = field(default_factory=dict)
    edges: List[Dict] = field(default_factory=list)

    def add_node(self, node_id: str, node_type: str, data: dict):
        self.nodes[node_id] = {"type": node_type, "data": data, "connections": []}

    def add_edge(
        self, from_id: str, to_id: str, relationship: str, weight: float = 1.0
    ):
        edge = {
            "from": from_id,
            "to": to_id,
            "relationship": relationship,
            "weight": weight,
            "created": datetime.utcnow().isoformat(),
        }
        self.edges.append(edge)
        if from_id in self.nodes:
            self.nodes[from_id]["connections"].append(to_id)
        if to_id in self.nodes:
            self.nodes[to_id]["connections"].append(from_id)


class Tropebook:
    def __init__(self, storage_path: str = "memory/tropebook/"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.citations_file = self.storage_path / "citations.json"
        self.graph_file = self.storage_path / "graph.json"
        self.index_file = self.storage_path / "index.json"
        self.citations: Dict[str, Citation] = {}
        self.graph = KnowledgeGraph()
        self._load()

    def _load(self):
        if self.citations_file.exists():
            with open(self.citations_file, "r") as f:
                data = json.load(f)
                self.citations = {k: Citation.from_dict(v) for k, v in data.items()}
        if self.graph_file.exists():
            with open(self.graph_file, "r") as f:
                data = json.load(f)
                self.graph = KnowledgeGraph(
                    nodes=data.get("nodes", {}), edges=data.get("edges", [])
                )
        if self.index_file.exists():
            with open(self.index_file, "r") as f:
                self._index = json.load(f)
        else:
            self._build_index()

    def _build_index(self):
        self._index = {"by_url": {}, "by_tag": {}, "by_entity": {}, "by_source": {}}
        for cid, cite in self.citations.items():
            if cite.url:
                self._index["by_url"][cite.url] = cid
            for tag in cite.tags:
                if tag not in self._index["by_tag"]:
                    self._index["by_tag"][tag] = []
                self._index["by_tag"][tag].append(cid)
            for entity in cite.entities:
                if entity not in self._index["by_entity"]:
                    self._index["by_entity"][entity] = []
                self._index["by_entity"][entity].append(cid)
            if cite.source_type:
                if cite.source_type not in self._index["by_source"]:
                    self._index["by_source"][cite.source_type] = []
                self._index["by_source"][cite.source_type].append(cid)
        self._save_index()

    def _save_index(self):
        with open(self.index_file, "w") as f:
            json.dump(self._index, f, indent=2)

    def add(
        self,
        title: str,
        url: str,
        summary: str = "",
        source: str = "",
        tags: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        source_type: SourceType = SourceType.MANUAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        if url in self._index["by_url"]:
            cid = self._index["by_url"][url]
            self.update(cid, summary=summary, tags=tags, entities=entities)
            return cid
        cid = str(uuid.uuid4())[:8]
        citation = Citation(
            title=title,
            url=url,
            summary=summary,
            source=source,
            tags=tags if tags is not None else [],
            entities=entities if entities is not None else [],
            source_type=source_type.value,
            metadata=metadata if metadata is not None else {},
        )
        self.citations[cid] = citation
        self.graph.add_node(cid, "citation", {"title": title, "url": url})
        self._build_index()
        self._save()
        return cid

    def update(self, cid: str, **kwargs):
        if cid in self.citations:
            cite = self.citations[cid]
            for key, value in kwargs.items():
                if hasattr(cite, key):
                    setattr(cite, key, value)
            self._build_index()
            self._save()

    def get(self, cid: str) -> Optional[Citation]:
        return self.citations.get(cid)

    def delete(self, cid: str) -> bool:
        """Delete a citation and its graph connections."""
        if cid not in self.citations:
            return False

        del self.citations[cid]

        for key in list(self._index.keys()):
            if cid in self._index[key]:
                self._index[key].pop(cid, None)

        self.graph.nodes.pop(cid, None)
        self.graph.edges = [
            e for e in self.graph.edges if e.get("from") != cid and e.get("to") != cid
        ]

        self._build_index()
        self._save()

        return True

    def find_by_url(self, url: str) -> Optional[Citation]:
        cid = self._index["by_url"].get(url)
        return self.citations.get(cid) if cid else None

    def find_by_tag(self, tag: str) -> List[Citation]:
        cids = self._index["by_tag"].get(tag, [])
        return [self.citations[cid] for cid in cids if cid in self.citations]

    def find_by_entity(self, entity: str) -> List[Citation]:
        cids = self._index["by_entity"].get(entity, [])
        return [self.citations[cid] for cid in cids if cid in self.citations]

    def find_by_source(self, source_type: SourceType) -> List[Citation]:
        cids = self._index["by_source"].get(source_type.value, [])
        return [self.citations[cid] for cid in cids if cid in self.citations]

    def link(self, cid1: str, cid2: str, relationship: str, weight: float = 1.0):
        self.graph.add_edge(cid1, cid2, relationship, weight)
        if cid1 in self.citations and cid2 in self.citations:
            self.citations[cid1].relationships.append(f"{cid2}:{relationship}")
            self.citations[cid2].relationships.append(f"{cid1}:{relationship}")
        self._save()

    def add_relationship(self, source_url: str, target_url: str, relationship: str):
        source = self.find_by_url(source_url)
        target = self.find_by_url(target_url)
        if source and target:
            self.link(
                list(self._index["by_url"].values())[
                    list(self._index["by_url"].keys()).index(source_url)
                ],
                list(self._index["by_url"].values())[
                    list(self._index["by_url"].keys()).index(target_url)
                ],
                relationship,
            )

    def search(self, query: str, limit: int = 20) -> List[Citation]:
        # Split query into words for better matching
        query_words = [w.lower() for w in query.split() if len(w) > 2]
        results = []
        for cite in self.citations.values():
            score = 0
            title_lower = cite.title.lower()
            summary_lower = cite.summary.lower()
            tags_lower = [t.lower() for t in cite.tags]

            for word in query_words:
                if word in title_lower:
                    score += 10
                if word in summary_lower:
                    score += 5
                if any(word in tag for tag in tags_lower):
                    score += 3

            if score > 0:
                results.append((score, cite))
        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def get_related(self, cid: str, depth: int = 1) -> Dict[str, Any]:
        if cid not in self.graph.nodes:
            return {}
        visited = set()
        layers = {0: [cid]}
        for d in range(depth):
            layers[d + 1] = []
            for node_id in layers[d]:
                if node_id in visited:
                    continue
                visited.add(node_id)
                connections = self.graph.nodes[node_id].get("connections", [])
                layers[d + 1].extend(connections)
        related = {}
        for node_id in visited:
            if node_id != cid and node_id in self.citations:
                related[node_id] = self.citations[node_id]
        return related

    def import_from_deep_research(self, data: dict) -> int:
        count = 0
        sources = data.get("sources", data.get("citations", []))
        for source in sources:
            if isinstance(source, dict):
                title = source.get("title", source.get("name", "Unknown"))
                url = source.get("url", source.get("link", ""))
                if url:
                    self.add(
                        title=title,
                        url=url,
                        summary=source.get("snippet", source.get("summary", "")),
                        source=source.get("source", ""),
                        tags=source.get("topics", source.get("tags", [])),
                        entities=source.get("entities", []),
                        source_type=SourceType.GOOGLE_DEEP_RESEARCH,
                        metadata=source,
                    )
                    count += 1
        return count

    def export_json(self) -> dict:
        return {
            "citations": {k: v.to_dict() for k, v in self.citations.items()},
            "graph": {"nodes": self.graph.nodes, "edges": self.graph.edges},
            "exported_at": datetime.utcnow().isoformat(),
        }

    def _save(self):
        with open(self.citations_file, "w") as f:
            json.dump({k: v.to_dict() for k, v in self.citations.items()}, f, indent=2)
        with open(self.graph_file, "w") as f:
            json.dump(
                {"nodes": self.graph.nodes, "edges": self.graph.edges}, f, indent=2
            )

    def stats(self) -> dict:
        return {
            "total_citations": len(self.citations),
            "by_source": {k: len(v) for k, v in self._index["by_source"].items()},
            "total_tags": len(self._index["by_tag"]),
            "total_entities": len(self._index["by_entity"]),
            "total_relationships": len(self.graph.edges),
        }

    def clear(self):
        """Clear all citations, graph, and index storage files."""
        import logging

        logger = logging.getLogger("tropelex.tropebook")
        logger.info("Clearing all data...")

        self.citations = {}
        self.graph = KnowledgeGraph()
        self._index = {"by_url": {}, "by_tag": {}, "by_entity": {}, "by_source": {}}

        # Delete storage files
        for f in [self.citations_file, self.graph_file, self.index_file]:
            if f.exists():
                try:
                    f.unlink()
                    logger.info(f"Deleted {f}")
                except Exception as e:
                    logger.warning(f"Could not delete {f}: {e}")

        logger.info("Clear complete")

    def merge_duplicates(self):
        url_to_cid = {}
        duplicates = []
        for cid, cite in self.citations.items():
            if cite.url in url_to_cid:
                duplicates.append((cid, url_to_cid[cite.url]))
            else:
                url_to_cid[cite.url] = cid
        for dup_cid, orig_cid in duplicates:
            self.link(dup_cid, orig_cid, "duplicate_of")
            del self.citations[dup_cid]
        self._build_index()
        self._save()
        return len(duplicates)
