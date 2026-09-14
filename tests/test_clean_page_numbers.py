"""Tests del cleaner de números de página (D6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    HeaderFooterCleaner,
    PageNumberCleaner,
    Pipeline,
    is_page_number_line,
    strip_page_number_lines,
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


# --- strip_page_number_lines ---


def test_strip_bare_number() -> None:
    assert strip_page_number_lines("foo\n47\nbar") == "foo\n\nbar"


def test_strip_em_dash() -> None:
    assert strip_page_number_lines("foo\n— 47 —\nbar") == "foo\n\nbar"


def test_strip_en_dash() -> None:
    assert strip_page_number_lines("foo\n– 47 –\nbar") == "foo\n\nbar"


def test_strip_hyphen() -> None:
    assert strip_page_number_lines("foo\n- 47 -\nbar") == "foo\n\nbar"


def test_strip_pipe_number_left() -> None:
    assert strip_page_number_lines("foo\n47 | Capítulo 3\nbar") == "foo\n\nbar"


def test_strip_pipe_number_right() -> None:
    assert strip_page_number_lines("foo\nCapítulo 3 | 47\nbar") == "foo\n\nbar"


def test_strip_mixed_lines() -> None:
    src = "foo\n47\nbar\n— 48 —\n49 | Cap 1\nbaz"
    assert strip_page_number_lines(src) == "foo\n\nbar\n\n\nbaz"


def test_strip_preserves_numbered_list_dot() -> None:
    assert strip_page_number_lines("1. foo\n2. bar") == "1. foo\n2. bar"


def test_strip_preserves_numbered_list_paren() -> None:
    assert strip_page_number_lines("1) foo\n2) bar") == "1) foo\n2) bar"


def test_strip_preserves_inline_reference() -> None:
    assert strip_page_number_lines("ver página 47") == "ver página 47"


def test_strip_preserves_inline_english_reference() -> None:
    assert strip_page_number_lines("see page 47") == "see page 47"


def test_strip_preserves_horizontal_rule() -> None:
    assert strip_page_number_lines("foo\n---\nbar") == "foo\n---\nbar"


def test_strip_preserves_year_alone() -> None:
    """Falso positivo documentado: año suelto se elimina."""
    assert strip_page_number_lines("foo\n2024\nbar") == "foo\n\nbar"


def test_strip_idempotent() -> None:
    samples = [
        "foo\n47\nbar",
        "— 47 —",
        "47 | Capítulo 3",
        "Capítulo 3 | 47",
        "plain text",
    ]
    for s in samples:
        once = strip_page_number_lines(s)
        twice = strip_page_number_lines(once)
        assert once == twice


def test_strip_empty_text() -> None:
    assert strip_page_number_lines("") == ""


def test_strip_no_page_numbers() -> None:
    src = "Lorem ipsum dolor sit amet.\nConsectetur adipiscing elit."
    assert strip_page_number_lines(src) == src


# --- is_page_number_line ---


@pytest.mark.parametrize(
    "line",
    [
        "47",
        "1234",
        "— 47 —",
        "– 47 –",
        "- 47 -",
        "47 | Capítulo 3",
        "Capítulo 3 | 47",
        "47|Capítulo 3",
    ],
)
def test_is_page_number_line_true_cases(line: str) -> None:
    assert is_page_number_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "1. foo",
        "2) bar",
        "---",
        "ver página 47",
        "see page 47",
        "foo",
        "Cap 47",
        "",
        "   ",
    ],
)
def test_is_page_number_line_false_cases(line: str) -> None:
    assert not is_page_number_line(line)


# --- PageNumberCleaner ---


def test_page_number_cleaner_default_name() -> None:
    from capmd.clean.page_numbers import DEFAULT_NAME

    assert PageNumberCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "page_numbers"


def test_page_number_cleaner_pipeline_integration(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(PageNumberCleaner(),))
    text, stats = pipeline.run("foo\n47\nbar", _ctx(tmp_path))
    assert text == "foo\n\nbar"
    assert len(stats) == 1
    assert stats[0].name == "page_numbers"
    assert stats[0].changes == 1


def test_page_number_cleaner_reports_count(tmp_path: Path) -> None:
    src = "foo\n47\nbar\n— 48 —\n49 | Cap 1"
    text, stats = Pipeline(cleaners=(PageNumberCleaner(),)).run(src, _ctx(tmp_path))
    assert text == "foo\n\nbar\n\n"
    assert stats[0].changes == 3


def test_page_number_cleaner_disabled(tmp_path: Path) -> None:
    src = "foo\n47\nbar"
    pipeline = Pipeline(cleaners=(PageNumberCleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_page_number_cleaner_empty_input(tmp_path: Path) -> None:
    result = PageNumberCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_page_number_cleaner_preserves_lists(tmp_path: Path) -> None:
    src = "1. primero\n2. segundo\n3. tercero"
    text, _stats = Pipeline(cleaners=(PageNumberCleaner(),)).run(src, _ctx(tmp_path))
    assert text == src


def test_page_number_cleaner_combined_with_d4(tmp_path: Path) -> None:
    """D4 elimina headers repetidos; D6 elimina los page numbers sueltos que quedan."""
    src = (
        "Header Comun\n"
        "Cuerpo del texto en página 1.\n"
        "— 1 —\n"
        "<!-- page 2 -->\n"
        "Header Comun\n"
        "Cuerpo del texto en página 2.\n"
        "— 2 —\n"
        "<!-- page 3 -->\n"
        "Header Comun\n"
        "Cuerpo del texto en página 3.\n"
        "— 3 —\n"
    )
    text, stats = Pipeline(cleaners=(HeaderFooterCleaner(), PageNumberCleaner())).run(
        src, _ctx(tmp_path)
    )

    assert "Header Comun" not in text
    assert "— 1 —" not in text
    assert "— 2 —" not in text
    assert "— 3 —" not in text
    assert "Cuerpo del texto en página 1." in text
    assert "Cuerpo del texto en página 3." in text
    assert stats[0].name == "headers"
    assert stats[1].name == "page_numbers"
