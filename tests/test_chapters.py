"""Tests de :func:`capmd.sources.chapters.resolve_chapter` (fase C5).

Lookup por índice (incluye sub-entradas) o por substring case-insensitive.
Errores: lista vacía, índice fuera de rango, 0 o >1 matches por substring.
"""

from __future__ import annotations

import pytest

from capmd.models import Chapter
from capmd.sources.chapters import resolve_chapter


def _ch(title: str, level: int, start: int, end: int, index: int) -> Chapter:
    return Chapter(title=title, level=level, start_page=start, end_page=end, index=index)


# Fixture alineado con build_outline_toc_pdf pero en memoria.
OUTLINE = [
    _ch("Chapter 1: Getting Started", level=1, start=1, end=2, index=1),
    _ch("1.1 Background", level=2, start=1, end=2, index=2),
    _ch("Chapter 2: Ownership", level=1, start=2, end=3, index=3),
    _ch("Chapter 3: Borrowing", level=1, start=3, end=4, index=4),
]


def test_resolve_by_index_returns_match() -> None:
    assert resolve_chapter(OUTLINE, "3").title == "Chapter 2: Ownership"


def test_resolve_by_index_includes_subentries() -> None:
    """El índice cuenta sub-entradas (index 2 = '1.1 Background', nivel 2)."""
    assert resolve_chapter(OUTLINE, "2").title == "1.1 Background"


def test_resolve_by_index_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="índice"):
        resolve_chapter(OUTLINE, "99")


def test_resolve_by_index_zero_or_negative_falls_back_to_substring() -> None:
    """``"0"`` y ``"-1"`` no son enteros positivos → busca substring (no matchea nada).

    Es un edge case raro pero el comportamiento queda definido:
    ``_try_int`` rechaza ``0`` y ``-1``, y el substring ``"0"``/``"-1"``
    no aparece en ningún título.
    """
    with pytest.raises(ValueError, match="ningún capítulo"):
        resolve_chapter(OUTLINE, "0")
    with pytest.raises(ValueError, match="ningún capítulo"):
        resolve_chapter(OUTLINE, "-1")


def test_resolve_by_substring_case_insensitive() -> None:
    assert resolve_chapter(OUTLINE, "ownership").title == "Chapter 2: Ownership"
    assert resolve_chapter(OUTLINE, "OWNERSHIP").title == "Chapter 2: Ownership"
    assert resolve_chapter(OUTLINE, "Own").title == "Chapter 2: Ownership"


def test_resolve_by_substring_partial_match() -> None:
    assert resolve_chapter(OUTLINE, "backgr").title == "1.1 Background"


def test_resolve_by_substring_no_match_raises() -> None:
    with pytest.raises(ValueError, match="ningún capítulo"):
        resolve_chapter(OUTLINE, "xyz")
    # El error lista los candidatos.
    with pytest.raises(ValueError, match="Chapter 1"):
        resolve_chapter(OUTLINE, "xyz")


def test_resolve_by_substring_ambiguous_raises() -> None:
    """``"Chapter"`` matchea 3 títulos → ambiguo."""
    with pytest.raises(ValueError, match="ambiguo"):
        resolve_chapter(OUTLINE, "Chapter")
    # La lista de candidatos incluye los índices.
    with pytest.raises(ValueError, match="Chapter 2: Ownership"):
        resolve_chapter(OUTLINE, "Chapter")


def test_resolve_empty_chapters_raises() -> None:
    with pytest.raises(ValueError, match="no tiene outline"):
        resolve_chapter([], "1")


def test_resolve_empty_spec_raises() -> None:
    with pytest.raises(ValueError, match="vacío"):
        resolve_chapter(OUTLINE, "")
    with pytest.raises(ValueError, match="vacío"):
        resolve_chapter(OUTLINE, "   ")


def test_resolve_whitespace_in_spec_trimmed() -> None:
    assert resolve_chapter(OUTLINE, " 3 ").title == "Chapter 2: Ownership"
    assert resolve_chapter(OUTLINE, " Ownership ").title == "Chapter 2: Ownership"


def test_resolve_numeric_string_with_extra_text_falls_back_to_substring() -> None:
    """``"3a"`` no parsea como int → busca substring."""
    with pytest.raises(ValueError, match="ningún capítulo"):
        resolve_chapter(OUTLINE, "3a")
