"""Tests unit del parser ``--chapters`` (H2)."""

from __future__ import annotations

import pytest

from capmd.sources.chapters import parse_chapters_spec


def test_single_index() -> None:
    assert parse_chapters_spec("1", total=12) == (1,)


def test_range() -> None:
    assert parse_chapters_spec("1-12", total=12) == tuple(range(1, 13))


def test_discrete_list() -> None:
    assert parse_chapters_spec("1,3,5", total=12) == (1, 3, 5)


def test_mixed() -> None:
    assert parse_chapters_spec("1-3,7,10-12", total=12) == (1, 2, 3, 7, 10, 11, 12)


def test_dedup() -> None:
    assert parse_chapters_spec("1,2,1,3", total=5) == (1, 2, 3)


def test_sorted_ascending() -> None:
    assert parse_chapters_spec("5,1,3,2", total=5) == (1, 2, 3, 5)


def test_whitespace_stripped() -> None:
    assert parse_chapters_spec(" 1 , 3 , 5 ", total=12) == (1, 3, 5)


def test_empty_spec() -> None:
    with pytest.raises(ValueError, match=r"vacío|--chapters"):
        parse_chapters_spec("", total=12)


def test_whitespace_only_spec() -> None:
    with pytest.raises(ValueError, match=r"vacío|nuevo"):
        parse_chapters_spec("   ", total=12)


def test_total_zero_or_negative() -> None:
    with pytest.raises(ValueError, match=r"outline|sin outline|sin TOC"):
        parse_chapters_spec("1", total=0)
    with pytest.raises(ValueError, match=r"outline|sin outline|sin TOC"):
        parse_chapters_spec("1", total=-1)


def test_index_zero() -> None:
    with pytest.raises(ValueError, match=r"1-indexed|0"):
        parse_chapters_spec("0", total=12)


def test_negative_index() -> None:
    with pytest.raises(ValueError, match=r"1-indexed|abierto|< 1|negativo"):
        parse_chapters_spec("-1", total=12)


def test_open_left() -> None:
    with pytest.raises(ValueError, match=r"abierto|abrir"):
        parse_chapters_spec("-1", total=12)


def test_open_right() -> None:
    with pytest.raises(ValueError, match=r"abierto|abrir"):
        parse_chapters_spec("1-", total=12)


def test_hyphen_only() -> None:
    with pytest.raises(ValueError, match=r"abierto|abrir"):
        parse_chapters_spec("-", total=12)


def test_descending_range() -> None:
    with pytest.raises(ValueError, match=r"descendente"):
        parse_chapters_spec("5-3", total=12)


def test_out_of_range_token() -> None:
    with pytest.raises(ValueError, match=r"fuera de rango"):
        parse_chapters_spec("1-100", total=12)


def test_out_of_range_single() -> None:
    with pytest.raises(ValueError, match=r"fuera de rango"):
        parse_chapters_spec("99", total=12)


def test_non_numeric() -> None:
    with pytest.raises(ValueError, match=r"numérico"):
        parse_chapters_spec("abc", total=12)


def test_range_with_one_side_out() -> None:
    with pytest.raises(ValueError, match=r"fuera de rango"):
        parse_chapters_spec("10-15", total=12)


def test_zero_in_range() -> None:
    with pytest.raises(ValueError, match=r"1-indexed|< 1|0"):
        parse_chapters_spec("0-3", total=12)
