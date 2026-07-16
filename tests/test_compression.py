"""Tests for core.compression.dictionary"""

from core.compression.dictionary import (
    STOP_WORDS,
    _apply_compact,
    _apply_phrases,
    _strip_stop_words,
    compress,
    compress_code_signatures,
    extract_signatures,
    summarize_long_text,
    truncate_to_tokens,
)


class TestDictionaryCompress:
    def test_level1_phrases_only(self):
        result = compress("could you please help me with implementing a function", level=1)
        assert "could you please" not in result
        assert "help" in result

    def test_level2_removes_filler(self):
        result = compress("I actually just need a simple function", level=2)
        assert "actually" not in result
        assert "just" not in result

    def test_level3_strips_stop_words(self):
        result = compress("the quick brown fox jumps over the lazy dog", level=3)
        # Stop words should be removed
        assert "the" not in result.split()

    def test_level0_no_change(self):
        text = "hello world"
        assert compress(text, level=0) == text

    def test_empty_string(self):
        assert compress("", level=2) == ""

    def test_whitespace_collapsed(self):
        result = compress("hello    world", level=1)
        assert "  " not in result


class TestPhraseRemaps:
    def test_i_would_like_to(self):
        result = _apply_phrases("i would like to build a function")
        assert "i would like to" not in result
        assert "build" in result

    def test_for_the_purpose_of(self):
        result = _apply_phrases("for the purpose of testing")
        assert "for the purpose of" not in result

    def test_could_you_please(self):
        result = _apply_phrases("could you please send the file")
        assert "could you please" not in result


class TestCompactPatterns:
    def test_removes_can_you(self):
        result = _apply_compact("can you do this")
        assert "can you" not in result

    def test_removes_please(self):
        result = _apply_compact("please help")
        assert "please" not in result


class TestStopWords:
    def test_removes_stop_words(self):
        result = _strip_stop_words("the cat is on the mat", aggressive=True)
        words = result.split()
        for word in words:
            assert word.lower() not in STOP_WORDS


class TestCodeSignatures:
    def test_extract_python_signatures(self):
        code = '''
def hello(name: str) -> str:
    return f"Hello {name}"

class Foo:
    def bar(self, x: int) -> bool:
        return x > 0
'''
        sigs = compress_code_signatures(code)
        assert "def hello" in sigs
        assert "class Foo" in sigs

    def test_empty_code(self):
        assert compress_code_signatures("") == ""


class TestTruncate:
    def test_short_text_unchanged(self):
        text = "short"
        assert truncate_to_tokens(text, 100) == text

    def test_long_text_truncated(self):
        text = "word " * 1000
        result = truncate_to_tokens(text, 10)
        assert len(result) < len(text)


class TestExtractSignatures:
    def test_python_signatures(self):
        code = "def foo(x, y):\n    pass\nclass Bar(Base):\n    pass"
        result = extract_signatures(code)
        assert "def foo" in result
        assert "class Bar" in result


class TestSummarizeLongText:
    def test_short_text_unchanged(self):
        text = "One sentence. Two sentence."
        assert summarize_long_text(text) == text

    def test_long_text_summarized(self):
        text = "First. " + ". ".join(["Middle sentence"] * 10) + ". Last."
        result = summarize_long_text(text)
        assert "First" in result
        assert "Last" in result
        assert len(result) < len(text)
