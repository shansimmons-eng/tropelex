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
    # ── Contraction/variant coverage for existing hedges above ──
    "i'd like to": "",
    "i'd like": "",
    "i'd prefer": "",
    "i would prefer": "",
    "i'd be": "",
    "i would be": "",
    # ── Purpose/time connectors ──
    "so as to": "to",
    "so that": "so",
    "right now": "now",
    "for the moment": "now",
    "just in case": "in case",
    "in spite of that": "still",
    "in spite of this": "still",
    "in regards to": "about",
    "in relation to": "about",
    # ── Preamble / throat-clearing ──
    "you probably recall": "",
    "if you recall": "",
    "i forgot to": "forgot to",
    "just to clarify": "clarify",
    "for clarity's sake": "for clarity",
    "one thing i noticed": "noticed",
    "i noticed that": "noticed",
    "thought i'd let you know": "",
    "once we get to that point": "",
    "once you get toward": "",
    "as we move towards": "",
    "as we move toward": "",
    # ── Wishes/preferences that add no decision content ──
    "i wish we could": "",
    "i wish you'd": "",
    "i wish you would": "",
    "i would love it if": "if",
    "i would like it if": "if",
    "i'm leaning toward": "leaning toward",
    "i am leaning toward": "leaning toward",
    "i'm leaning towards": "leaning towards",
    "i am leaning towards": "leaning towards",
    # ── Politeness directives (verb-preserving) ──
    "please take into account": "consider",
    "please be aware": "note",
    "please remember": "remember",
    "kindly": "",
    # ── Completion timing ──
    "once you're done": "once done",
    "when you finish": "once done",
    "when that's complete": "once done",
    # ── Deadline framing — compresses the wind-up, keeps the actual due date/time that follows ──
    "i have to get this done by": "due by",
    "i have to get this done before": "due before",
    "i have to complete this by": "due by",
    "i have to fix this by": "due by",
    "i have to do this by": "due by",
    "i have to turn this in by": "due by",
    "get this done by": "due by",
    "the deadline is": "deadline",
    "this is due by": "due by",
    "this is due": "due",
    # ── Gratitude / sign-offs (pure social nicety, safe regardless of context) ──
    "much appreciated": "",
    "i can't thank you enough": "",
    "can't thank you enough": "",
    "i am so grateful": "",
    "i'd really appreciate it if": "",
    "i would really appreciate it if": "",
    "i'd really appreciate it": "",
    "i would really appreciate it": "",
    "i'd really appreciate that": "",
    "i would really appreciate that": "",
    "i'd appreciate it if": "",
    "i would appreciate it if": "",
    "i'd appreciate that": "",
    "i would appreciate that": "",
    "thanks for all of your help": "thanks",
    "thanks for all your help": "thanks",
    "thanks for all the help": "thanks",
    # ── Greetings / small talk / affirmations — zero task content ──
    "let's take a break": "",
    "let's stop here": "",
    "it's bedtime": "",
    "good morning": "",
    "hello sir": "",
    "yes sir": "",
    "yessir": "",
    "you bet ya": "yes",
    "sure thing": "yes",
    "hell yeah": "yes",
    "hell yes": "yes",
    # ── Bare interjections — emotional emphasis, no informational content ──
    "good lord": "",
    "oh my god": "",
    "ohmygod": "",
    "omg": "",
    # ── Additional filler not in the original set — same "zero semantic
    # payload" bar as everything above ──
    "if it's not too much trouble": "",
    "when you get a chance": "",
    "no rush": "",
    "at your earliest convenience": "when you can",
    "whenever you have a moment": "",
    "if you don't mind": "",
    "just a heads up": "heads up",
    "quick question": "question",
    "real quick": "",
    "to make a long story short": "in short",
    "long story short": "in short",
    "to cut to the chase": "in short",
    "the bottom line is": "bottom line",
    "at the end of the day": "ultimately",
    "when all is said and done": "ultimately",
    "for what it's worth": "",
    "just so you know": "",
    "just so we're clear": "to clarify",
    "to be honest": "",
    "if i'm being honest": "",
    "if i'm honest": "",
    "sorry to bother you": "",
    "sorry to be a pain": "",
    "my apologies": "",
    "my bad": "",
    # ── Uncertainty markers — shortened, not deleted: the compressed form
    # must still signal "user hasn't decided," or the agent reading it will
    # wrongly treat an open question as a settled instruction ──
    "not sure which": "unsure which",
    "not sure about that": "unsure about that",
    "i'm not sure": "unsure",
    "i'm not certain": "uncertain",
    "i don't know yet": "TBD",
    "i have no idea": "no idea",
    "i have no clue": "no clue",
    "i don't know about that": "unsure about that",
    "i don't know what to do next": "next steps unclear",
    "any ideas about": "ideas on",
    "what do you suggest": "suggestions",
    "what would you suggest": "suggestions",
    "how would you go about": "how to",
    "how should i go about": "how to",
    "not able to recall": "can't recall",
    "i can't remember": "can't remember",
    "i don't remember": "don't remember",
    "i don't have access": "no access",
    "i can't find": "can't find",
    "i have no preference": "no preference",
    "it's your call": "your call",
    # ── Real questions — shortened, kept as questions. "how do we"/"is
    # there a way to" collapse to "how to" (still asks for a method, not
    # an action — different from "can you", which asks for the action
    # itself). Contractions preserve the past-tense auxiliary that a
    # blind strip of "did" would break ("how did we" -> "how we" is
    # ungrammatical; "how'd we" isn't). ──
    "how do we": "how to",
    "is there a way to": "how to",
    "how did we": "how'd we",
    "when did we": "when'd we",
    "what did we": "what'd we",
    "what do you think": "thoughts",
    "what are your thoughts": "thoughts",
    "when's a good time": "best time",
    "when is a good time": "best time",
    "tell me a good time": "best time",
    "tell me when it's best": "best time",
    "find me some": "find",
    "give me details on": "details on",
    "what's the status": "status",
    "what is the status": "status",
    # ── Substantive descriptors — trimmed, meaning intact ──
    "a key factor": "key factor",
    "a big part of": "big part of",
    "critically important": "critical",
    "the one thing": "one thing",
    "more than i can handle": "too much",
    # ── Task-framing context — compressed to a short label instead of a
    # full sentence, not deleted (the fact that it's a boss request or a
    # new task is real information) ──
    "my boss asked for": "boss wants",
    "i have a new task": "new task",
    "i have a new assignment": "new assignment",
    "i have a new request": "new request",
    "help with an assignment": "assignment help",
    # ── Urgency / deadline-pressure — canonicalized to a short marker
    # rather than deleted. This is a real priority signal; collapsing five
    # different phrasings ("this is a big deal"/"this is huge"/"this is a
    # huge deal"/"this is massive") to one consistent marker is arguably
    # better than the original, since an agent parsing many compressed
    # prompts sees one recognizable flag instead of five variants ──
    "this is urgent": "urgent",
    "this is a big deal": "high priority",
    "this is huge": "high priority",
    "this is a huge deal": "high priority",
    "this is massive": "high priority",
    "i don't have much time": "time-limited",
    "i do not have much time": "time-limited",
    "i'm running out of time": "time-limited",
    "i've run out of time": "out of time",
    "i have run out of time": "out of time",
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
    # ── Request-opener strips: word-boundary only, so the real verb that
    # follows ("...find the file", "...convert this") survives intact.
    # Whole-phrase entries like "can you find" belong in PHRASE_REMAPS only
    # when the entire phrase is disposable — these aren't, since "find"/
    # "convert"/etc. carry the actual request. ──
    r"\bcan we\b": "",
    r"\bwill you\b": "",
    r"\bwould you\b": "",
    r"\bcould you\b": "",
    r"\bmay i\b": "",
    r"\bi have to\b": "",
    r"\bi need to\b": "",
    r"\bi've got to\b": "",
    r"\bi have got to\b": "",
    r"\bbe able to\b": "",
    r"\bi wonder if (?:you|we)\b": "",
    r"\bis it possible to\b": "",
    r"\bwould it be possible to\b": "",
    r"\bdid you\b": "",
    r"\bi need help\b": "",
    r"\bi was hoping you(?:'d| could)\b": "",
    r"\bhoping you(?:'d| could)\b": "",
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
        # Case-insensitive whole-phrase replace. Leading \b only (not
        # trailing) — every phrase here starts with a word character, so a
        # leading boundary is always safe and stops short entries like
        # "etc" from matching mid-word (e.g. inside "betcha", "sketch").
        # A trailing \b isn't added: phrases ending in punctuation (e.g.
        # "etc.") would never match real prose, where "etc. " is followed
        # by whitespace — both sides of that boundary are non-word, so \b
        # can't match there at all.
        text = re.sub(r"\b" + re.escape(phrase), replacement, text, flags=re.IGNORECASE)
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
