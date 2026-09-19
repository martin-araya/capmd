"""Tests del parser ``parse_pages`` (fase C4).

Cubre cada sintaxis del roadmap, edge cases y validación de bounds.
"""

from __future__ import annotations

import pytest

from capmd.errors import RangeOutOfBounds
from capmd.models import PageRange
from capmd.sources.pages import parse_pages, translate_spec


def _pages(spec: str, total: int = 100) -> list[int]:
    return list(parse_pages(spec, total_pages=total).pages)


def test_single_page() -> None:
    assert _pages("42") == [42]


def test_closed_range() -> None:
    assert _pages("45-78") == list(range(45, 79))


def test_open_right_resolves_to_total() -> None:
    assert _pages("45-", total=50) == list(range(45, 51))


def test_open_left_resolves_to_one() -> None:
    assert _pages("-30", total=50) == list(range(1, 31))


def test_open_both_raises() -> None:
    with pytest.raises(ValueError, match="rango abierto"):
        _pages("-", total=10)


def test_comma_list() -> None:
    assert _pages("12,15,20-25", total=30) == [12, 15, 20, 21, 22, 23, 24, 25]


def test_whitespace_tolerated() -> None:
    assert _pages(" 45 - 78 , 100 ", total=100) == [*list(range(45, 79)), 100]


def test_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="vacío"):
        _pages("")


def test_whitespace_only_raises() -> None:
    with pytest.raises(ValueError, match="vacío"):
        _pages("   ")


def test_zero_page_raises() -> None:
    with pytest.raises(ValueError, match="1-indexed"):
        _pages("0")


def test_zero_in_range_raises() -> None:
    with pytest.raises(ValueError, match="1-indexed"):
        _pages("0-5")


def test_descending_range_raises() -> None:
    with pytest.raises(ValueError, match="descendente"):
        _pages("78-45")


def test_double_dash_raises() -> None:
    with pytest.raises(ValueError, match="demasiados"):
        _pages("45--78")


def test_non_numeric_raises() -> None:
    with pytest.raises(ValueError, match="page spec"):
        _pages("abc")


def test_empty_tokens_ignored() -> None:
    """``45,,78`` se interpreta como ``45,78`` (más amigable que fallar)."""
    assert _pages("45,,78") == [45, 78]


def test_out_of_bounds_raises_range_out_of_bounds() -> None:
    with pytest.raises(RangeOutOfBounds):
        _pages("100", total=50)


def test_open_right_out_of_bounds_raises() -> None:
    with pytest.raises(RangeOutOfBounds):
        _pages("40-", total=30)


def test_returns_page_range_instance() -> None:
    result = parse_pages("1-3", total_pages=10)
    assert isinstance(result, PageRange)


def test_pages_are_sorted_and_unique() -> None:
    """El resultado siempre está ordenado y deduplicado."""
    result = parse_pages("50, 50-52, 30", total_pages=100)
    assert list(result.pages) == sorted(set(result.pages))
    assert 50 in result.pages
    assert len(result.pages) == len(set(result.pages))


def test_total_pages_zero_raises() -> None:
    with pytest.raises(ValueError, match="total_pages"):
        parse_pages("1", total_pages=0)


# --- FIX-5 / D5: validación end > total_pages ---


def test_pages_end_out_of_bounds_raises_rangeoutofbounds() -> None:
    """FIX-5: ``--pages 1-99`` en PDF de 18pp debe fallar con
    RangeOutOfBounds antes de llegar al motor (antes daba IndexError)."""
    with pytest.raises(RangeOutOfBounds) as excinfo:
        parse_pages("1-99", total_pages=18)
    assert excinfo.value.exit_code == 4
    msg = excinfo.value.message
    assert "18" in msg
    assert "1-18" in msg


def test_pages_inverse_range_descending_rejected() -> None:
    """FIX-5: ``--pages 10-3`` (start > end, rango descendente) falla
    con ValueError descriptivo, NO con IndexError."""
    with pytest.raises(ValueError, match="rango descendente"):
        parse_pages("10-3", total_pages=20)


def test_pages_exact_boundary_is_valid() -> None:
    """FIX-5 regresión: ``--pages 1-18`` en PDF de 18pp es válido."""
    result = parse_pages("1-18", total_pages=18)
    assert list(result.pages) == list(range(1, 19))


def test_pages_end_just_above_boundary() -> None:
    """FIX-5: ``--pages 1-19`` en PDF de 18pp falla (un solo page de más)."""
    with pytest.raises(RangeOutOfBounds):
        parse_pages("1-19", total_pages=18)


def test_pages_comma_list_with_one_out_of_range() -> None:
    """FIX-5: lista con un rango fuera de bounds → falla."""
    with pytest.raises(RangeOutOfBounds):
        parse_pages("1-5,10-99", total_pages=20)


# --- C7: translate_spec ---------------------------------------------------


def test_translate_no_op_for_zero_offset() -> None:
    assert translate_spec("45-78,12", offset=0) == "45-78,12"


def test_translate_positive_offset_closed_range() -> None:
    """Test literal del roadmap: offset 18 + '45-50' → '63-68'."""
    assert translate_spec("45-50", offset=18) == "63-68"


def test_translate_positive_offset_open_right_preserves_open() -> None:
    assert translate_spec("45-", offset=18) == "63-"


def test_translate_positive_offset_open_left_preserves_open() -> None:
    assert translate_spec("-30", offset=18) == "-48"


def test_translate_negative_offset() -> None:
    assert translate_spec("50-60", offset=-5) == "45-55"


def test_translate_list_mixed() -> None:
    assert translate_spec("12,15,20-25", offset=18) == "30,33,38-43"


def test_translate_invalid_token_raises() -> None:
    with pytest.raises(ValueError, match="número no entero"):
        translate_spec("abc", offset=18)


def test_translate_preserves_whitespace_in_open_sides() -> None:
    """El lado abierto se preserva como string vacío dentro del split."""
    result = translate_spec("-30", offset=10)
    # Re-parseable: el open left sigue funcionando.
    pages = parse_pages(result, total_pages=100).pages
    assert pages == tuple(range(1, 41))
