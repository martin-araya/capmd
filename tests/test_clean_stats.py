"""Tests de :func:`count_diff`."""

from __future__ import annotations

from capmd.clean._stats import count_diff


def test_count_diff_identical() -> None:
    assert count_diff("hola\n", "hola\n") == 0
    assert count_diff("", "") == 0


def test_count_diff_insertion_only() -> None:
    assert count_diff("", "abc") == 3
    assert count_diff("", "abc\nxyz\n") == 2


def test_count_diff_deletion_only() -> None:
    assert count_diff("abc", "") == 1
    assert count_diff("a\nb\nc\n", "") == 3


def test_count_diff_single_line_len_change() -> None:
    assert count_diff("abc", "abcd") == 1
    assert count_diff("abcd", "abc") == 1


def test_count_diff_multiline_set_xor() -> None:
    assert count_diff("a\nb\nc\n", "a\n") >= 1
    assert count_diff("a\nb\nc\n", "a\nd\n") >= 2


def test_count_diff_totally_different() -> None:
    assert count_diff("hola", "adios") >= 1
