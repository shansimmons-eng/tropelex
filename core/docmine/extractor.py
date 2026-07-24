"""Claim extraction from markdown text — pure functions, no I/O.

Pulls out decision-shaped, checkable statements from markdown: list items,
table cells, and paragraph sentences. Skips headers, code blocks, pure
links/images/badges, and anything too short to be a meaningful claim.
"""

from __future__ import annotations

import hashlib
import re

from core.docmine import DocClaim

_MIN_CLAIM_LENGTH = 25

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_HEADER_RE = re.compile(r"^\s*#{1,6}\s")
_HRULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_PURE_LINK_RE = re.compile(r"^\s*\[!?\[.*?\]\(.*?\)\]\(.*?\)\s*$|^\s*!?\[.*?\]\(.*?\)\s*$")
_MD_SYNTAX_RE = re.compile(r"[*_`#]|\[([^\]]*)\]\([^)]*\)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[`])")


def _strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", text)


def _clean_claim_text(raw: str) -> str:
    """Strip markdown syntax down to plain, comparable text."""
    text = _MD_SYNTAX_RE.sub(lambda m: m.group(1) or "", raw)
    return re.sub(r"\s+", " ", text).strip()


def _claim_id(source_file: str, line_number: int, text: str) -> str:
    raw = f"{source_file}:{line_number}:{text}"
    return "claim-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def extract_claims(text: str, source_file: str) -> list[DocClaim]:
    """Extract candidate claims from a markdown document.

    Pure function: same input always produces the same output, no I/O.
    """
    claims: list[DocClaim] = []
    body = _strip_code_fences(text)

    for line_number, raw_line in enumerate(body.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if _HEADER_RE.match(line) or _HRULE_RE.match(line):
            continue
        if _PURE_LINK_RE.match(line.strip()):
            continue

        list_match = _LIST_ITEM_RE.match(line)
        if list_match:
            claim_text = _clean_claim_text(list_match.group(1))
            if len(claim_text) >= _MIN_CLAIM_LENGTH:
                claims.append(DocClaim(
                    id=_claim_id(source_file, line_number, claim_text),
                    text=claim_text,
                    source_file=source_file,
                    line_number=line_number,
                ))
            continue

        table_match = _TABLE_ROW_RE.match(line)
        if table_match:
            if _TABLE_SEP_RE.match(line):
                continue
            # Join cells into one claim — a lone cell ("GET", "Optional")
            # has no context to compare against; the row as a whole does.
            cells = [_clean_claim_text(c) for c in table_match.group(1).split("|")]
            claim_text = " — ".join(c for c in cells if c)
            if len(claim_text) >= _MIN_CLAIM_LENGTH:
                claims.append(DocClaim(
                    id=_claim_id(source_file, line_number, claim_text),
                    text=claim_text,
                    source_file=source_file,
                    line_number=line_number,
                ))
            continue

        # Plain paragraph line — split into sentences.
        cleaned = _clean_claim_text(line)
        for sentence in _SENTENCE_SPLIT_RE.split(cleaned):
            sentence = sentence.strip()
            if len(sentence) >= _MIN_CLAIM_LENGTH:
                claims.append(DocClaim(
                    id=_claim_id(source_file, line_number, sentence),
                    text=sentence,
                    source_file=source_file,
                    line_number=line_number,
                ))

    return claims
