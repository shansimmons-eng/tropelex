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

    def test_id_like_to_contraction(self):
        result = _apply_phrases("i'd like to refactor the auth module")
        assert "i'd like to" not in result
        assert "refactor" in result

    def test_deadline_phrase_preserves_the_actual_date(self):
        result = _apply_phrases("I have to get this done by Friday")
        assert result == "due by Friday"

    def test_leaning_towards_not_mangled_by_shorter_leaning_toward_entry(self):
        # "i'm leaning toward" is a literal prefix of "i'm leaning towards" —
        # regression test for the trailing "s" surviving intact.
        result = _apply_phrases("i'm leaning towards option B")
        assert result == "leaning towards option B"

    def test_gratitude_phrase_with_leading_i_not_left_dangling(self):
        # Regression: "can't thank you enough" is a substring of "i can't
        # thank you enough" — the shorter entry must not fire first and
        # leave a dangling "i " behind.
        result = _apply_phrases("I can't thank you enough for the help")
        assert result.strip() not in ("I", "i")
        assert "can't thank you enough" not in result.lower()

    def test_you_betcha_not_corrupted_by_bare_etc_entry(self):
        # Regression: the bare "etc" entry has no word boundaries and is a
        # literal substring of "betcha" (b-ETC-ha) — must not mangle it.
        result = _apply_phrases("you betcha")
        assert "..." not in result

    def test_thank_you_for_all_help_variant_still_collapses(self):
        # No dedicated "thank you for all X help" entry exists (removed as
        # dead code — shadowed by the earlier bare "thank you for" entry),
        # but the two-step cascade through "thanks for all X help" -> "thanks"
        # must still fully collapse it.
        result = _apply_phrases("Thank you for all of your help")
        assert result == "thanks"


class TestCompactPatterns:
    def test_removes_can_you(self):
        result = _apply_compact("can you do this")
        assert "can you" not in result

    def test_removes_please(self):
        result = _apply_compact("please help")
        assert "please" not in result

    def test_removes_would_you_preserves_verb(self):
        result = _apply_compact("would you convert this file")
        assert "would you" not in result
        assert "convert" in result

    def test_removes_could_you(self):
        result = _apply_compact("could you check the logs")
        assert "could you" not in result
        assert "check" in result

    def test_be_able_to_fixes_would_you_be_able_to_compound(self):
        # Regression: "would you" alone stripped first would leave a
        # dangling "be able to" — "be able to" must also be stripped so the
        # whole opener collapses down to just the verb.
        result = _apply_compact("would you be able to convert this to JSON")
        assert "be able to" not in result
        assert "convert" in result

    def test_removes_i_have_to_preserves_verb(self):
        result = _apply_compact("i have to fix this bug")
        assert "i have to" not in result
        assert "fix" in result


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


class TestShortenedNotDeleted:
    """Phrases that look like filler but carry real meaning: shortened to a
    compact form that preserves the signal, never dropped to "" outright.
    Regression coverage for a correction — an earlier pass wrongly excluded
    these instead of shortening them."""

    def test_uncertainty_marker_preserved(self):
        result = _apply_phrases("Not sure which approach to take")
        assert "unsure" in result.lower()
        assert "which" in result

    def test_urgency_signal_preserved_as_canonical_marker(self):
        result = _apply_phrases("This is a huge deal for the client")
        assert "high priority" in result
        assert "for the client" in result

    def test_time_pressure_signal_preserved(self):
        result = _apply_phrases("I'm running out of time on this")
        assert "time-limited" in result

    def test_past_tense_question_uses_contraction_not_broken_grammar(self):
        result = _apply_phrases("How did we end up with two auth systems")
        assert result == "how'd we end up with two auth systems"

    def test_how_do_we_preserves_process_question_not_action_request(self):
        # "how do we deploy this" asks for a method; must not collapse to
        # "deploy this" (an instruction), which would change the meaning.
        result = _apply_phrases("How do we deploy this safely")
        assert "how to deploy this safely" == result.lower()

    def test_is_it_possible_to_strips_opener_keeps_verb(self):
        result = _apply_compact("Is it possible to add retry logic")
        assert "is it possible to" not in result.lower()
        assert "add retry logic" in result

    def test_did_you_strips_opener_keeps_verb(self):
        result = _apply_compact("Did you find the missing config")
        assert "did you" not in result.lower()
        assert "find the missing config" in result

    def test_critically_important_shortens_to_critical(self):
        result = _apply_phrases("Critically important that we test this")
        assert result == "critical that we test this"
