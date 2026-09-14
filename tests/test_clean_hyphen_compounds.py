"""Tests del mapa de compuestos hyphenados."""

from __future__ import annotations

import pytest

from capmd.clean._hyphen_compounds import COMPOUND_EXCEPTIONS


def test_compound_exceptions_minimum_size() -> None:
    assert len(COMPOUND_EXCEPTIONS) >= 100


def test_compound_exceptions_format() -> None:
    pattern = __import__("re").compile(r"^\w+(-\w+)+$")
    for compound in COMPOUND_EXCEPTIONS:
        assert pattern.match(compound), f"{compound!r} no encaja en \\w+(-\\w+)+"


def test_compound_exceptions_lowercase_only() -> None:
    for compound in COMPOUND_EXCEPTIONS:
        assert compound == compound.lower(), f"{compound!r} no es lowercase"


@pytest.mark.parametrize(
    "compound",
    [
        "well-known",
        "self-contained",
        "long-term",
        "high-level",
        "self-aware",
        "cost-of-living",
        "state-of-the-art",
        "out-of-the-box",
        "real-time",
        "part-time",
        "open-source",
        "non-functional",
    ],
)
def test_known_compounds_present(compound: str) -> None:
    assert compound in COMPOUND_EXCEPTIONS


def test_known_compounds_no_duplicates() -> None:
    assert len(COMPOUND_EXCEPTIONS) == len(set(COMPOUND_EXCEPTIONS))
