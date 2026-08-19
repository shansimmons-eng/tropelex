"""Domain models for RepoSeek — immutable dataclasses for search queries and results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RepoResult:
    """A single repository match returned by a RepoSeek query.

    Attributes:
        title: Repository name (owner/repo format).
        url: Full GitHub URL to the repository.
        description: Short repo description from the API.
        language: Primary programming language (may be None).
        stars: Current star count.
        similarity_score: Float 0-1 indicating relevance to the query.
        match_reasons: Human-readable explanations of why this repo matched.
    """

    title: str
    url: str
    description: str
    language: str | None
    stars: int
    similarity_score: float
    match_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (safe for JSON, no circular refs)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RepoResult:
        """Deserialize from a dict, ignoring unknown keys."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class SeekQuery:
    """Parameters for a RepoSeek search request.

    Attributes:
        query: Natural-language description of what to find.
        language: Restrict results to this language (None = any).
        topics: GitHub topic tags to filter on.
    """

    query: str
    language: str | None = None
    topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return asdict(self)
