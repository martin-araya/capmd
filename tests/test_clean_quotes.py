"""Tests del mapa de comillas exóticas y curly estándar."""

from __future__ import annotations

import pytest

from capmd.clean._quotes import RARE_QUOTES_MAP, STANDARD_CURLY_QUOTES

EXPECTED_RARE = {
    "‚": ",",
    "‛": "'",
    "„": '"',
    "‟": '"',
    "′": "'",
    "″": '"',
    "‴": "'''",
    "‵": "'",
    "‶": '"',
    "«": '"',
    "»": '"',
    "‹": "'",
    "›": "'",
    "ʼ": "'",
    "ʻ": "'",
}


def test_rare_quotes_map_has_expected_entries() -> None:
    assert set(RARE_QUOTES_MAP.keys()) == set(EXPECTED_RARE.keys())
    assert dict(RARE_QUOTES_MAP) == EXPECTED_RARE


def test_rare_quotes_map_size() -> None:
    assert len(RARE_QUOTES_MAP) == 15


@pytest.mark.parametrize(
    ("char", "replacement"),
    [
        ("‚", ","),
        ("‛", "'"),
        ("„", '"'),
        ("‟", '"'),
        ("′", "'"),
        ("″", '"'),
        ("‴", "'''"),
        ("‵", "'"),
        ("‶", '"'),
        ("«", '"'),
        ("»", '"'),
        ("‹", "'"),
        ("›", "'"),
        ("ʼ", "'"),
        ("ʻ", "'"),
    ],
)
def test_rare_quotes_individual_mapping(char: str, replacement: str) -> None:
    assert RARE_QUOTES_MAP[char] == replacement


def test_standard_curly_quotes_are_not_in_rare_map() -> None:
    assert STANDARD_CURLY_QUOTES.isdisjoint(RARE_QUOTES_MAP.keys())
    assert "\u2018" in STANDARD_CURLY_QUOTES
    assert "\u2019" in STANDARD_CURLY_QUOTES
    assert "\u201c" in STANDARD_CURLY_QUOTES
    assert "\u201d" in STANDARD_CURLY_QUOTES
