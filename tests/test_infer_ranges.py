"""Tests de :func:`capmd.sources.pdf.infer_ranges` (fase C3).

Cubre: rangos contiguos sin solapes ni huecos para nivel 1, anidamiento
de sub-entradas, edge cases (lista vacía, una sola entrada, total
menor al inicio), y preservación de la inmutabilidad del input.
"""

from __future__ import annotations

import pytest

from capmd.models import Chapter
from capmd.sources.pdf import infer_ranges


def _ch(title: str, level: int, start: int, index: int) -> Chapter:
    """Helper: chapter con ``end_page = start_page`` (placeholder)."""
    return Chapter(title=title, level=level, start_page=start, end_page=start, index=index)


def test_last_chapter_extends_to_total_pages() -> None:
    chapters = [_ch("Only", level=1, start=1, index=1)]
    out = infer_ranges(chapters, total_pages=3)
    assert len(out) == 1
    assert out[0].end_page == 4
    assert out[0].end_page_inclusive == 3


def test_middle_chapter_extends_to_next_l1() -> None:
    chapters = [
        _ch("A", level=1, start=1, index=1),
        _ch("B", level=1, start=5, index=2),
    ]
    out = infer_ranges(chapters, total_pages=10)
    assert out[0].end_page == 5  # A cierra en B.start (exclusivo)
    assert out[0].end_page_inclusive == 4
    assert out[1].end_page == 11  # B cierra en total+1
    assert out[1].end_page_inclusive == 10


def test_subentry_nests_under_parent() -> None:
    """Una entrada nivel 2 cierra con su ancestro, no con el L1 siguiente."""
    chapters = [
        _ch("Ch1", level=1, start=1, index=1),
        _ch("1.1", level=2, start=2, index=2),
        _ch("Ch2", level=1, start=5, index=3),
    ]
    out = infer_ranges(chapters, total_pages=10)
    assert out[0].end_page == 5  # Ch1 cierra en Ch2.start
    assert out[1].end_page == 5  # 1.1 cierra en Ch2.start (level 1 <= 2)
    assert out[2].end_page == 11  # Ch2 cierra en total+1


def test_contiguous_no_overlap_no_gap_l1() -> None:
    """Invariante del roadmap: rangos L1 contiguos, sin solapes, sin huecos."""
    chapters = [
        _ch("A", level=1, start=1, index=1),
        _ch("B", level=1, start=4, index=2),
        _ch("C", level=1, start=7, index=3),
        _ch("D", level=1, start=10, index=4),
    ]
    total = 12
    out = infer_ranges(chapters, total_pages=total)

    # Cada L1 cierra donde abre el siguiente (contigüidad).
    assert out[0].end_page == out[1].start_page == 4
    assert out[1].end_page == out[2].start_page == 7
    assert out[2].end_page == out[3].start_page == 10
    # El último cierra en total+1.
    assert out[3].end_page == total + 1


def test_empty_input_returns_empty() -> None:
    assert infer_ranges([], total_pages=10) == []


def test_total_pages_smaller_than_last_start_raises() -> None:
    chapters = [_ch("X", level=1, start=5, index=1)]
    with pytest.raises(ValueError, match="outline"):
        infer_ranges(chapters, total_pages=1)


def test_total_pages_zero_raises() -> None:
    chapters = [_ch("X", level=1, start=1, index=1)]
    with pytest.raises(ValueError, match="total_pages"):
        infer_ranges(chapters, total_pages=0)


def test_returns_new_list_does_not_mutate_input() -> None:
    chapters = [
        _ch("A", level=1, start=1, index=1),
        _ch("B", level=1, start=5, index=2),
    ]
    snapshot = [(c.title, c.start_page, c.end_page, c.index) for c in chapters]
    _ = infer_ranges(chapters, total_pages=10)
    after = [(c.title, c.start_page, c.end_page, c.index) for c in chapters]
    assert snapshot == after, "infer_ranges mutó la lista de entrada"


def test_index_and_chapter_instances_preserved() -> None:
    chapters = [
        _ch("A", level=1, start=1, index=1),
        _ch("B", level=1, start=5, index=2),
    ]
    out = infer_ranges(chapters, total_pages=10)
    assert all(isinstance(c, Chapter) for c in out)
    assert [c.index for c in out] == [1, 2]
    assert [c.title for c in out] == ["A", "B"]


def test_deeply_nested_subentries_close_at_first_lower_or_equal_level() -> None:
    """L3 dentro de L2 dentro de L1: cada uno cierra donde cierra el nivel
    superior más cercano."""
    chapters = [
        _ch("Ch1", level=1, start=1, index=1),
        _ch("1.1", level=2, start=2, index=2),
        _ch("1.1.1", level=3, start=3, index=3),
        _ch("Ch2", level=1, start=10, index=4),
    ]
    out = infer_ranges(chapters, total_pages=15)
    assert out[0].end_page == 10  # Ch1 cierra en Ch2.start
    assert out[1].end_page == 10  # 1.1 también (siguiente con level <= 2)
    assert out[2].end_page == 10  # 1.1.1 también
    assert out[3].end_page == 16  # Ch2 cierra en total+1
