"""Tests del cleaner de footnotes (D13)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    FootnotesCleaner,
    Pipeline,
    detect_footnote_block,
    normalize_markers,
    parse_footnote_definitions,
    render_gfm_footnotes,
    repair_footnotes,
)
from capmd.clean.footnotes import (
    BRACKET_MARKER_RE,
    DEFAULT_NAME,
    SUPERSCRIPT_DIGITS,
    SUPERSCRIPT_RE,
)
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


# --- SUPERSCRIPT_DIGITS ---


def test_superscript_digits_map_size() -> None:
    assert len(SUPERSCRIPT_DIGITS) == 10


@pytest.mark.parametrize(
    "char",
    ["⁰", "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"],
)
def test_superscript_digits_present(char: str) -> None:
    assert char in SUPERSCRIPT_DIGITS


# --- normalize_markers: supers ---


def test_superscript_single_digit() -> None:
    text, _ = normalize_markers("texto¹")
    assert text == "texto[^1]"


def test_superscript_two_digits_split() -> None:
    text, _ = normalize_markers("texto¹²")
    assert text == "texto[^1][^2]"


def test_superscript_zero() -> None:
    text, _ = normalize_markers("cafe⁰")
    assert text == "cafe[^0]"


def test_superscript_in_word_unchanged_if_glued() -> None:
    """Supers pegado a una letra SÍ se reemplaza (típico en PDFs)."""
    text, _ = normalize_markers("cafe²")
    assert text == "cafe[^2]"


# --- normalize_markers: brackets ---


def test_bracket_marker_at_end_of_line() -> None:
    text, _ = normalize_markers("texto. [1]")
    assert text == "texto. [^1]"


def test_bracket_marker_with_trailing_space() -> None:
    text, _ = normalize_markers("texto.  [1]")
    assert text == "texto.  [^1]"


def test_bracket_marker_in_middle_unchanged() -> None:
    text, _ = normalize_markers("texto [1] más texto")
    assert text == "texto [1] más texto"


def test_bracket_marker_in_link_unchanged() -> None:
    text, _ = normalize_markers("click [here](url)")
    assert text == "click [here](url)"


def test_bracket_marker_multidigit() -> None:
    text, _ = normalize_markers("text [12]")
    assert text == "text [^12]"


def test_bracket_marker_at_end_of_text() -> None:
    text, _ = normalize_markers("text [1]")
    assert text == "text [^1]"


def test_normalize_preserves_fence() -> None:
    text, _ = normalize_markers("before\n```\ntexto¹\n```\nafter")
    assert "texto¹" in text
    assert "[^1]" not in text.split("```")[1]


# --- detect_footnote_block ---


def test_detect_footnote_block_three_items() -> None:
    text = "intro\n\n1. First\n2. Second\n3. Third"
    block = detect_footnote_block(text)
    assert block is not None
    start, end = block
    extracted = text.splitlines()[start:end]
    assert "1. First" in extracted[0]


def test_detect_footnote_block_no_block() -> None:
    assert detect_footnote_block("Solo texto sin items.") is None


def test_detect_footnote_block_with_blanks_between() -> None:
    text = "intro\n\n1. A\n\n2. B\n\n3. C"
    block = detect_footnote_block(text)
    assert block is not None
    start, end = block
    assert end - start >= 5


def test_detect_footnote_block_only_at_end() -> None:
    text = "1. Not at end\n\nBody.\n\n2. A\n3. B"
    block = detect_footnote_block(text)
    assert block is not None
    start, end = block
    extracted = text.splitlines()[start:end]
    assert "2. A" in extracted[0]


def test_detect_footnote_block_with_trailing_blank() -> None:
    text = "1. A\n2. B\n\n"
    block = detect_footnote_block(text)
    assert block is not None


# --- parse_footnote_definitions ---


def test_parse_three_definitions() -> None:
    text = "intro\n\n1. First note\n2. Second\n3. Third"
    notes = parse_footnote_definitions(text)
    assert notes == {1: "First note", 2: "Second", 3: "Third"}


def test_parse_with_paren_style() -> None:
    text = "1) Foo\n2) Bar"
    notes = parse_footnote_definitions(text)
    assert notes == {1: "Foo", 2: "Bar"}


def test_parse_no_block() -> None:
    assert parse_footnote_definitions("Solo texto.") == {}


# --- render_gfm_footnotes ---


def test_render_basic() -> None:
    out = render_gfm_footnotes({1: "First", 2: "Second"})
    assert "[^1]: First" in out
    assert "[^2]: Second" in out


def test_render_empty() -> None:
    assert render_gfm_footnotes({}) == ""


def test_render_sorted() -> None:
    out = render_gfm_footnotes({3: "C", 1: "A", 2: "B"})
    lines = out.splitlines()
    assert lines[0] == "[^1]: A"
    assert lines[1] == "[^2]: B"
    assert lines[2] == "[^3]: C"


# --- repair_footnotes ---


def test_repair_three_notes_roadmap() -> None:
    """Caso literal del roadmap."""
    src = (
        "Texto uno¹ y dos². Más texto³.\n\n"
        "1. Primera nota sobre uno\n"
        "2. Segunda nota sobre dos\n"
        "3. Tercera nota sobre tres"
    )
    out, n_markers, n_defs = repair_footnotes(src)
    # 3 markers en body + 3 en defs (cada def empieza con [^N])
    marker_refs = re.findall(r"\[\^\d+\](?!:)", out)
    def_refs = re.findall(r"\[\^\d+\]:", out)
    assert len(marker_refs) == 3
    assert len(def_refs) == 3
    assert "[^1]: Primera nota sobre uno" in out
    assert "[^2]: Segunda nota sobre dos" in out
    assert "[^3]: Tercera nota sobre tres" in out
    assert n_markers >= 3
    assert n_defs == 3


def test_repair_preserves_existing_definitions() -> None:
    src = "text[^1]\n\n[^1]: existing definition"
    out, _, _ = repair_footnotes(src)
    assert "[^1]: existing definition" in out


def test_repair_preserves_orphan_marker() -> None:
    src = "text[^99] sin def"
    out, _, _ = repair_footnotes(src)
    assert "[^99]" in out


def test_repair_preserves_orphan_definition() -> None:
    src = "text\n\n[^7]: definition sin marker"
    out, _, _ = repair_footnotes(src)
    assert "[^7]: definition sin marker" in out


def test_repair_dedupes_adjacent_refs() -> None:
    """Si el mismo número aparece dos veces (supers + bracket), dedupe."""
    src = "texto [1] ¹"
    out, _, _ = repair_footnotes(src)
    marker_refs = re.findall(r"\[\^\d+\](?!:)", out)
    assert len(marker_refs) == 1


def test_repair_combined_supers_and_brackets() -> None:
    src = "text¹ [1]"
    out, _, _ = repair_footnotes(src)
    assert out.count("[^1]") == 1


def test_repair_empty_text() -> None:
    out, _, _ = repair_footnotes("")
    assert out == ""


def test_repair_no_footnotes_intact() -> None:
    src = "Texto sin notas al pie."
    out, _, _ = repair_footnotes(src)
    assert out == src


def test_repair_keeps_body_intact() -> None:
    src = "intro para uno¹.\n\n1. nota"
    out, _, _ = repair_footnotes(src)
    assert "intro para uno[^1]." in out


def test_repair_only_block_no_markers() -> None:
    """Si hay bloque al final pero ningún marker, no se hace nada."""
    src = "intro\n\n1. A\n2. B"
    out, _, _ = repair_footnotes(src)
    # el bloque se preserva como estaba (sin markers, no se reorganiza)
    assert "1. A" in out
    assert "2. B" in out


# --- FootnotesCleaner ---


def test_footnotes_cleaner_default_name() -> None:
    assert FootnotesCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "footnotes"


def test_footnotes_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(FootnotesCleaner(), Cleaner)


def test_footnotes_cleaner_pipeline_integration(tmp_path: Path) -> None:
    src = "texto¹\n\n1. nota"
    pipeline = Pipeline(cleaners=(FootnotesCleaner(),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert "[^1]" in text
    assert "[^1]: nota" in text
    assert stats[0].name == "footnotes"


def test_footnotes_cleaner_disabled(tmp_path: Path) -> None:
    src = "texto¹\n\n1. nota"
    pipeline = Pipeline(cleaners=(FootnotesCleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_footnotes_cleaner_empty_input(tmp_path: Path) -> None:
    result = FootnotesCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_footnotes_cleaner_no_change_when_no_footnotes(tmp_path: Path) -> None:
    src = "Just plain text without notes."
    result = FootnotesCleaner().run(src, _ctx(tmp_path))
    assert result.text == src
    assert result.changes == 0


def test_footnotes_cleaner_reports_count(tmp_path: Path) -> None:
    src = "Texto uno¹ y dos². Tres³.\n\n1. a\n2. b\n3. c"
    result = FootnotesCleaner().run(src, _ctx(tmp_path))
    assert result.changes >= 6  # 3 markers + 3 defs


# --- constants ---


def test_superscript_re_compiles() -> None:
    assert SUPERSCRIPT_RE.search("a¹")
    assert SUPERSCRIPT_RE.search("a¹²")
    assert not SUPERSCRIPT_RE.search("abc")
    assert not SUPERSCRIPT_RE.search("a2")


def test_bracket_marker_re_matches_end_of_line() -> None:
    assert BRACKET_MARKER_RE.search("text [1]\n")
    assert BRACKET_MARKER_RE.search("text [1]")
    assert not BRACKET_MARKER_RE.search("text [1] more")
