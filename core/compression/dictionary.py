"""
Tropelex Compression Dictionary
Stop words, phrase rephrases, and meta language for prompt compression.
"""
import re

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "their", "we", "our", "you", "your", "he", "she", "him", "her",
    "i", "me", "my", "what", "which", "who", "whom", "when", "where",
    "why", "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "also", "now", "here", "there",
}

PHRASE_REMAPS = {
    "please provide": "give",
    "please help": "help",
    "please could you": "please",
    "i would like to": "i want",
    "i need to": "need to",
    "i want to": "want to",
    "could you please": "please",
    "would you mind": "please",
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
    "feel free to": "you can",
    "i hope this helps": "",
    "thank you for": "thanks for",
    "best regards": "",
    "sincerely": "",
    "kind regards": "",
    "looking forward to": "期待",
    "quick note": "",
    "just wanted to": "",
    "fyi": "",
    "asap": "",
    "etc": "...",
    "for example": "e.g.",
    "that is to say": "i.e.",
    "in other words": "i.e.",
    "note that": "",
    "please note": "",
    "keep in mind": "remember",
    "just to be clear": "clarify",
}

META_COMMANDS = {
    "//!": "stop_word_strip",
    ">>": "compress_whitespace",
    "??": "dedupe",
    "@@": "truncate_to",
    "##": "section",
    "<<<": "keep_recent",
    ">>>": "keep_all",
    "---": "horizontal_rule",
    "===": "section_break",
}

META_PATTERNS = [
    (r'\[STOP\]', ''),
    (r'\[DEDUP\]', ''),
    (r'\[SUMMarize\]', ''),
    (r'\[SIG\]', 'extract_signature'),
    (r'\[KEEP\s+(\d+)\]', r'keep_last_\1'),
]

COMPACT_PATTERNS = {
    r'\bcan you\b': 'you',
    r'\bplease\b': '',
    r'\bthank you\b': '',
    r'\bsorry\b': '',
    r'\bactually\b': '',
    r'\bbasically\b': '',
    r'\bjust\b': '',
    r'\bmaybe\b': '',
    r'\bprobably\b': '',
    r'\breally\b': '',
    r'\bvery\b': '',
    r'\bquite\b': '',
    r'\bkind of\b': '',
    r'\bsort of\b': '',
    r'\bdefinitely\b': '',
}

REPLIES = {
    "thanks": "np",
    "thank you": "np",
    "appreciate it": "np",
    "sorry": "np",
    "no problem": "np",
    "you're welcome": "np",
}

def compress(text: str, level: int = 1) -> str:
    if level <= 0:
        return text
    
    text = _strip_stop_words(text, aggressive=(level >= 3))
    text = _apply_phrases(text)
    text = _apply_compact(text)
    
    return text

def _strip_stop_words(text: str, aggressive: bool = False) -> str:
    words = text.split()
    if aggressive:
        filtered = [w for w in words if w.lower() not in STOP_WORDS]
    else:
        filtered = [w if w.lower() not in STOP_WORDS else '' for w in words]
    
    result = ' '.join(w for w in filtered if w)
    return result

def _apply_phrases(text: str) -> str:
    for phrase, replacement in PHRASE_REMAPS.items():
        text = text.replace(phrase, replacement)
    return text

def _apply_compact(text: str) -> str:
    for pattern, replacement in COMPACT_PATTERNS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text

def parse_meta(text: str) -> str:
    result = text
    for cmd, action in META_COMMANDS.items():
        if cmd in result:
            result = result.replace(cmd, '')
    return result.strip()

def extract_meta(text: str) -> tuple[str, list[str]]:
    commands = []
    for cmd in META_COMMANDS:
        if cmd in text:
            commands.append(cmd)
    
    clean = parse_meta(text)
    return clean, commands

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
    functions = re.findall(r'(def|class|interface|struct)\s+(\w+)\s*\([^)]*\)', code)
    signatures = [f"{match[0]} {match[1]}(...)" for match in functions[:max_functions]]
    return '\n'.join(signatures) if signatures else code

def summarize_long_text(text: str, max_length: int = 500) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) <= 3:
        return text
    
    first = sentences[0]
    last = sentences[-1]
    middle_count = len(sentences) - 2
    
    summary = f"{first}\n\n... [{middle_count} intermediate entries] ...\n\n{last}"
    return summary if len(summary) < max_length else text[:max_length] + "..."