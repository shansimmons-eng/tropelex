"""
Tropelex Compression Dictionary
Stop words, phrase remaps, and meta language for prompt compression.
"""

import re

STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "as",
    "is",
    "was",
    "are",
    "were",
    "been",
    "be",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "shall",
    "can",
    "need",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "they",
    "them",
    "their",
    "we",
    "our",
    "you",
    "your",
    "he",
    "she",
    "him",
    "her",
    "i",
    "me",
    "my",
    "what",
    "which",
    "who",
    "whom",
    "when",
    "where",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "also",
    "now",
    "here",
    "there",
}

SIGNATURE_PATTERNS = [
    (r"def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?", r"def \1(\2) -> \3"),
    (
        r"async\s+def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?",
        r"async def \1(\2) -> \3",
    ),
    (r"class\s+(\w+)(?:\s*\(([^)]+)\))?", r"class \1(\2)"),
    (r"interface\s+(\w+)(?:\s*<([^>]+)>)?", r"interface \1<\2>"),
    (r"type\s+(\w+)\s*=", r"type \1 ="),
    (r"const\s+(\w+)\s*=", r"const \1 ="),
    (r"let\s+(\w+)\s*=", r"let \1 ="),
    (r"var\s+(\w+)\s*=", r"var \1 ="),
]

PHRASE_REMAPS = {
    "please provide": "give",
    "please help": "help",
    "please could you": "",
    "i would like to": "",
    "i need to": "",
    "i want to": "",
    "could you please": "",
    "would you mind": "",
    "in order to": "to",
    "in the process of": "while",
    "at this point in time": "now",
    "for the purpose of": "to",
    "in the event that": "if",
    "on the other hand": "however",
    "in addition to this": "also",
    "as a result of": "so",
    "with regard to": "about",
    "in spite of the fact that": "although",
    "for the reason that": "because",
    "due to the fact that": "because",
    "in order to ensure": "to ensure",
    "it is important to note": "notably",
    "it should be noted that": "notably",
    "let me know if": "tell me if",
    "feel free to": "",
    "i hope this helps": "",
    "thank you for": "thanks for",
    "best regards": "",
    "sincerely": "",
    "kind regards": "",
    "looking forward to": "anticipating",
    "quick note": "",
    "just wanted to": "",
    "for example": "e.g.",
    "that is to say": "i.e.",
    "in other words": "i.e.",
    "note that": "",
    "please note": "",
    "keep in mind": "remember",
    "just to be clear": "clarify:",
    "etc.": "...",
    "etc": "...",
    "asap": "immediately",
    "fyi": "",
}

META_COMMANDS = {
    "//!": "stop_word_strip",
    ">>": "compress_whitespace",
    "??": "dedupe",
    "@@": "truncate_to",
    "##": "section",
    "<<<": "keep_recent",
    ">>>": "keep_all",
}

COMPACT_PATTERNS = {
    r"\bcan you\b": "",
    r"\bplease\b": "",
    r"\bthank you\b": "",
    r"\bthanks\b": "",
    r"\bsorry\b": "",
    r"\bactually\b": "",
    r"\bbasically\b": "",
    r"\bjust\b": "",
    r"\bmaybe\b": "",
    r"\bprobably\b": "",
    r"\breally\b": "",
    r"\bvery\b": "",
    r"\bquite\b": "",
    r"\bkind of\b": "",
    r"\bsort of\b": "",
    r"\bdefinitely\b": "",
}


def compress(text: str, level: int = 1) -> str:
    if level <= 0:
        return text
    text = _apply_phrases(text)
    if level >= 2:
        text = _apply_compact(text)
    if level >= 3:
        text = _strip_stop_words(text, aggressive=True)
    text = re.sub(r"  +", " ", text).strip()
    return text


def compress_code_signatures(code: str, max_signatures: int = 30) -> str:
    """Extract only function/method signatures from code, drop bodies."""
    signatures = []
    for line in code.split("\n"):
        for pattern, replacement in SIGNATURE_PATTERNS:
            match = re.search(pattern, line)
            if match:
                sig = _build_signature(match, replacement)
                if sig and len(signatures) < max_signatures:
                    signatures.append(sig)
                break
    return "\n".join(signatures) if signatures else code


def _build_signature(match: re.Match, template: str) -> str:
    groups = match.groups()
    result = template
    for i, group in enumerate(groups, 1):
        result = result.replace(f"\\{i}", group.strip() if group else "")
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"[,\s]+->", " ->", result)
    result = re.sub(r"[,\s]+\)", ")", result)
    return result.strip()


def truncate_to_tokens(text: str, max_tokens: int, priority: str = "recent") -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[-max_chars:] if priority == "recent" else text[:max_chars]


def _strip_stop_words(text: str, aggressive: bool = False) -> str:
    """Remove stop words. Uses token-level matching so punctuation-attached words are handled."""

    def _clean(word: str) -> str:
        # Strip leading/trailing punctuation for comparison only
        bare = re.sub(r"^[^\w]+|[^\w]+$", "", word).lower()
        if bare in STOP_WORDS:
            return "" if aggressive else ""
        return word

    words = text.split()
    filtered = [w for w in (_clean(w) for w in words) if w]
    return " ".join(filtered)


def _apply_phrases(text: str) -> str:
    for phrase, replacement in PHRASE_REMAPS.items():
        # Case-insensitive whole-phrase replace
        text = re.sub(re.escape(phrase), replacement, text, flags=re.IGNORECASE)
    return text


def _apply_compact(text: str) -> str:
    for pattern, replacement in COMPACT_PATTERNS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def parse_meta(text: str) -> str:
    for cmd in META_COMMANDS:
        text = text.replace(cmd, "")
    return text.strip()


def extract_meta(text: str) -> tuple:
    commands = [cmd for cmd in META_COMMANDS if cmd in text]
    return parse_meta(text), commands


def build_compressed_prompt(parts: list[str], meta: str = "") -> str:
    sections = []
    if meta:
        sections.append(f"[META: {meta}]")
    for part in parts:
        if part.strip():
            compressed = compress(part)
            if compressed:
                sections.append(compressed)
    return "\n".join(sections)


def extract_signatures(code: str, max_functions: int = 20) -> str:
    functions = re.findall(r"(def|class|interface|struct)\s+(\w+)\s*\([^)]*\)", code)
    signatures = [f"{m[0]} {m[1]}(...)" for m in functions[:max_functions]]
    return "\n".join(signatures) if signatures else code


def summarize_long_text(text: str, max_length: int = 500) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= 3:
        return text
    first = sentences[0]
    last = sentences[-1]
    mid = len(sentences) - 2
    summary = f"{first}\n\n... [{mid} intermediate entries] ...\n\n{last}"
    return summary if len(summary) < max_length else text[:max_length] + "..."
