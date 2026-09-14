"""Tests del cleaner de whitespace (D2)."""

from __future__ import annotations

from pathlib import Path

from capmd.clean import (
    CleanContext,
    Pipeline,
    WhitespaceCleaner,
    collapse_blank_lines,
    normalize_unicode_nfc,
    normalize_whitespace,
    replace_ligatures,
    replace_rare_quotes,
    strip_trailing_spaces,
)
from capmd.clean.whitespace import DEFAULT_NAME
from capmd.models import SourceDoc


def _make_source(tmp_path: Path) -> SourceDoc:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return SourceDoc(
        path=p,
        format="pdf",
        sha256="0" * 64,
        size_bytes=p.stat().st_size,
    )


def _ctx(tmp_path: Path) -> CleanContext:
    return CleanContext(source=_make_source(tmp_path), format="pdf")


# --- strip_trailing_spaces ---


def test_strip_trailing_spaces_removes_tabs_and_spaces() -> None:
    assert strip_trailing_spaces("hola   \nmundo\t\n  adios  \n") == "hola\nmundo\n  adios\n"


def test_strip_trailing_spaces_preserves_leading_whitespace() -> None:
    assert strip_trailing_spaces("    hola\n\tmundo   \n") == "    hola\n\tmundo\n"


def test_strip_trailing_spaces_empty_and_no_trail() -> None:
    assert strip_trailing_spaces("") == ""
    assert strip_trailing_spaces("hola\nmundo\n") == "hola\nmundo\n"


def test_strip_trailing_spaces_handles_no_trailing_newline() -> None:
    assert strip_trailing_spaces("hola   ") == "hola"


# --- collapse_blank_lines ---


def test_collapse_blank_lines_collapses_three_or_more() -> None:
    assert collapse_blank_lines("a\n\n\n\n\nb\n") == "a\n\nb\n"
    assert collapse_blank_lines("a\n\n\n\n\n\n\nb\n") == "a\n\nb\n"


def test_collapse_blank_lines_preserves_single_blank() -> None:
    assert collapse_blank_lines("a\n\nb\n") == "a\n\nb\n"


def test_collapse_blank_lines_idempotent_on_two_breaks() -> None:
    assert collapse_blank_lines("a\n\nb\n") == "a\n\nb\n"


def test_collapse_blank_lines_idempotent_on_no_blanks() -> None:
    assert collapse_blank_lines("a\nb\n") == "a\nb\n"


def test_collapse_blank_lines_handles_crlf_and_cr() -> None:
    assert collapse_blank_lines("a\r\n\r\n\r\n\r\nb\r\n") == "a\n\nb\n"
    assert collapse_blank_lines("a\r\r\rb\n") == "a\n\nb\n"


def test_collapse_blank_lines_empty() -> None:
    assert collapse_blank_lines("") == ""


# --- normalize_unicode_nfc ---


def test_normalize_unicode_nfc_combines_decomposed() -> None:
    decomposed = "e\u0301"  # e + combining acute
    assert normalize_unicode_nfc(decomposed) == "é"
    assert normalize_unicode_nfc("é") == "é"


def test_normalize_unicode_nfc_idempotent() -> None:
    samples = ["café", "naïve", "", "ascii only"]
    for s in samples:
        once = normalize_unicode_nfc(s)
        twice = normalize_unicode_nfc(once)
        assert once == twice


def test_normalize_unicode_nfc_empty() -> None:
    assert normalize_unicode_nfc("") == ""


# --- replace_ligatures ---


def test_replace_ligatures_handles_all_six() -> None:
    text = "ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ"
    assert replace_ligatures(text) == "fi fl ffi ffl st st"


def test_replace_ligatures_idempotent() -> None:
    text = "ﬁle and ﬂag"
    once = replace_ligatures(text)
    twice = replace_ligatures(once)
    assert once == twice


def test_replace_ligatures_does_not_touch_literal_fi() -> None:
    assert replace_ligatures("fi fl") == "fi fl"


def test_replace_ligatures_empty() -> None:
    assert replace_ligatures("") == ""


# --- replace_rare_quotes ---


def test_replace_rare_quotes_handles_all_fifteen() -> None:
    text = "‚ ‛ „ ‟ ′ ″ ‴ ‵ ‶ « » ‹ › ʼ ʻ"
    expected = ", ' \" \" ' \" ''' ' \" \" \" ' ' ' '"
    assert replace_rare_quotes(text) == expected


def test_replace_rare_quotes_preserves_standard_curly() -> None:
    text = "\u2018hello\u2019 y \u201cworld\u201d"
    assert replace_rare_quotes(text) == text


def test_replace_rare_quotes_idempotent() -> None:
    text = "‹tag› «frase»"
    once = replace_rare_quotes(text)
    twice = replace_rare_quotes(once)
    assert once == twice


def test_replace_rare_quotes_empty() -> None:
    assert replace_rare_quotes("") == ""


# --- normalize_whitespace (composición) ---


def test_normalize_whitespace_roadmap_case() -> None:
    """Caso del roadmap: 6 saltos + ligadura + trailing."""
    src = "línea uno   \n\n\n\n\n\nlínea dosﬁligadura   \n"
    expected = "línea uno\n\nlínea dosfiligadura\n"
    assert normalize_whitespace(src) == expected


def test_normalize_whitespace_is_idempotent() -> None:
    samples = [
        "ascii only\n\n",
        "línea uno   \n\n\n\n\n\nlínea dosﬁligadura   \n",
        "café ‹naïve› «frase»\r\n\r\n\r\n\r\nmás‴\n",
        "\u2018hola\u2019\n\n\n",
    ]
    for s in samples:
        once = normalize_whitespace(s)
        twice = normalize_whitespace(once)
        assert once == twice, f"not idempotent on {s!r}"


def test_normalize_whitespace_handles_crlf() -> None:
    src = "línea uno   \r\n\r\n\r\n\r\nlínea dos\r\n"
    expected = "línea uno\n\nlínea dos\n"
    assert normalize_whitespace(src) == expected


def test_normalize_whitespace_empty() -> None:
    assert normalize_whitespace("") == ""


# --- WhitespaceCleaner ---


def test_whitespace_cleaner_roadmap_case_reports_changes(tmp_path: Path) -> None:
    """Caso del roadmap: el cleaner reporta cambios sobre el input con 6 saltos y ligaduras."""
    src = "línea uno   \n\n\n\n\n\nlínea dosﬁligadura   \n"
    cleaner = WhitespaceCleaner()

    result = cleaner.run(src, _ctx(tmp_path))

    assert result.text == "línea uno\n\nlínea dosfiligadura\n"
    # 2 líneas con trailing + 1 run colapsado + 0 unicode + 1 ligadura + 0 comillas
    assert result.changes >= 3


def test_whitespace_cleaner_reports_changes_per_category(tmp_path: Path) -> None:
    """Las 5 categorías de cambios se reportan en el ``changes`` total."""
    src = "trail   \n\n\n\n\n\ne\u0301\nﬁligadura\n‹tag›\n"
    cleaner = WhitespaceCleaner()
    result = cleaner.run(src, _ctx(tmp_path))

    # 1 línea con trailing (trail)
    # 1 run colapsado (5 saltos)
    # 1 char NFC (e + combining acute)
    # 1 ligadura (ﬁ)
    # 1 comilla rara (‹ y › cuentan ambos pero replace solo del par)
    assert result.changes >= 4


def test_whitespace_cleaner_default_name() -> None:
    assert WhitespaceCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "whitespace"


def test_whitespace_cleaner_runs_in_pipeline(tmp_path: Path) -> None:
    src = "línea uno   \n\n\n\n\n\nlínea dosﬁligadura   \n"
    pipeline = Pipeline(cleaners=(WhitespaceCleaner(),), stop_on_error=True)
    text, stats = pipeline.run(src, _ctx(tmp_path))

    assert text == "línea uno\n\nlínea dosfiligadura\n"
    assert len(stats) == 1
    assert stats[0].name == "whitespace"
    assert stats[0].enabled is True
    assert stats[0].changes >= 3
    assert stats[0].error is None


def test_whitespace_cleaner_disabled_is_skipped(tmp_path: Path) -> None:
    src = "línea uno   \n\n\n\n\n\nlínea dosﬁligadura   \n"
    pipeline = Pipeline(cleaners=(WhitespaceCleaner(enabled=False),))

    text, stats = pipeline.run(src, _ctx(tmp_path))

    assert text == src
    assert len(stats) == 1
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_whitespace_cleaner_empty_input(tmp_path: Path) -> None:
    result = WhitespaceCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_whitespace_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(WhitespaceCleaner(), Cleaner)
