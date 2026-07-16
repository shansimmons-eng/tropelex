"""
Tropelex Context Compressor
Trims prompts on the fly while preserving signal.
"""

import re
from dataclasses import dataclass

from ..compression.dictionary import (
    compress as dictionary_compress,
)
from ..compression.dictionary import (
    compress_code_signatures,
    extract_meta,
    extract_signatures,
    summarize_long_text,
    truncate_to_tokens,
)


@dataclass
class CompressionResult:
    content: str
    original_length: int
    compressed_length: int
    compression_ratio: float
    removed_chunks: list[str]
    strategy_used: str = "none"


class ContextCompressor:
    """
    Compresses context for prompt optimization.
    Strategies:
    1. Dictionary-based compression with meta commands
    2. Remove redundant whitespace/formatting
    3. Truncate long code blocks to signatures
    4. Collapse repeated patterns
    5. Prioritize recent over historical
    """

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.avg_chars_per_token = 4

    def compress(
        self, content: str, priority: str = "recent", level: int = 1
    ) -> CompressionResult:
        """
        Compress content while preserving signal.
        priority: 'recent' keeps latest, 'all' keeps equally distributed
        level: 1=light, 2=medium, 3=aggressive stop word removal
        """
        original_length = len(content)
        strategy = "none"

        # Step 0: Apply dictionary compression if meta commands present
        content, commands = extract_meta(content)
        if commands or level > 1:
            content = dictionary_compress(content, level)
            strategy = f"dictionary_l{level}"

        # Step 1: Detect and compress code blocks
        content, code_sig_count = self._compress_code_blocks(content)
        if code_sig_count > 0:
            strategy = f"code_signatures({code_sig_count})"

        # Step 2: Remove redundant whitespace
        content = self._collapse_whitespace(content)

        # Step 3: Remove duplicate lines/sections
        content = self._remove_duplicates(content)

        # Step 4: Truncate if still too long
        if len(content) > self.max_tokens * self.avg_chars_per_token:
            content = truncate_to_tokens(content, self.max_tokens, priority)
            strategy = f"truncate_{priority}"

        compressed_length = len(content)
        removed = original_length - compressed_length

        return CompressionResult(
            content=content,
            original_length=original_length,
            compressed_length=compressed_length,
            compression_ratio=removed / original_length if original_length > 0 else 0,
            removed_chunks=commands,
            strategy_used=strategy,
        )

    def _compress_code_blocks(self, text: str) -> tuple[str, int]:
        """Find code blocks and compress to signatures if they're long."""
        code_block_pattern = r"```[\w]*\n(.*?)```"
        count = 0

        def replace_block(match):
            nonlocal count
            code = match.group(1)
            if len(code) > 300:
                count += 1
                compressed = compress_code_signatures(code)
                return f"```\n{compressed}\n```"
            return match.group(0)

        compressed = re.sub(code_block_pattern, replace_block, text, flags=re.DOTALL)
        return compressed, count

    def _collapse_whitespace(self, text: str) -> str:
        # Collapse multiple blank lines into one
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Collapse multiple spaces into one (but preserve indentation)
        lines = text.split("\n")
        collapsed = []
        for line in lines:
            # Preserve leading whitespace for indentation
            match = re.match(r"^(\s+)(.*)", line)
            if match:
                indent = match.group(1)
                content = match.group(2)
                collapsed_line = indent + re.sub(r" +", " ", content)
            else:
                collapsed_line = re.sub(r" +", " ", line)
            collapsed.append(collapsed_line)
        return "\n".join(collapsed)

    def _remove_duplicates(self, text: str) -> str:
        lines = text.split("\n")
        seen = set()
        unique = []
        for line in lines:
            # Normalize for comparison (lowercase, stripped)
            normalized = line.lower().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(line)
            elif not normalized:
                unique.append(line)
        return "\n".join(unique)

    def _truncate(self, text: str, priority: str) -> str:
        return truncate_to_tokens(text, self.max_tokens, priority)

    def extract_signatures(self, code: str, max_functions: int = 20) -> str:
        """
        Extract function/class signatures from code, drop body.
        Useful when only type signatures are needed.
        """
        return extract_signatures(code, max_functions)

    def summarize_long_text(self, text: str, max_length: int = 500) -> str:
        """
        Summarize long text by keeping first and last sentences.
        Good for logs, history, etc.
        """
        return summarize_long_text(text, max_length)

    def extract_key_decisions(self, text: str, max_decisions: int = 10) -> str:
        """
        Extract lines that look like decisions: starts with -, *, or contains keywords.
        """
        lines = text.split("\n")
        decisions = []
        keywords = [
            "decided",
            "chose",
            "selected",
            "built",
            "created",
            "fixed",
            "removed",
            "updated",
        ]

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "• ")):
                if any(kw in stripped.lower() for kw in keywords):
                    decisions.append(stripped)

        return "\n".join(decisions[:max_decisions])
