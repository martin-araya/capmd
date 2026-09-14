"""Tests del mapa y reemplazo de ligaduras."""

from __future__ import annotations

from capmd.clean._ligatures import LIGATURES_MAP

EXPECTED = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}


def test_map_has_expected_entries() -> None:
    assert set(LIGATURES_MAP.keys()) == set(EXPECTED.keys())
    assert dict(LIGATURES_MAP) == EXPECTED


def test_map_size() -> None:
    assert len(LIGATURES_MAP) == 6


def test_keys_are_ligatures() -> None:
    for key in LIGATURES_MAP:
        assert 0xFB00 <= ord(key) <= 0xFB06, f"{key!r} not in U+FB00–U+FB06"
