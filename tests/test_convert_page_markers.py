"""Tests de centinelas de página (D5)."""

from __future__ import annotations

import pytest

from capmd.convert.page_markers import (
    PAGE_MARKER_RE,
    PAGE_MARKER_TEMPLATE,
    insert_page_markers,
    join_pages,
    split_by_page_markers,
    strip_page_markers,
)


def test_insert_page_markers_empty_list() -> None:
    assert insert_page_markers([]) == ""


def test_insert_page_markers_single_page_no_marker() -> None:
    assert insert_page_markers(["only"]) == "only"


def test_insert_page_markers_three_pages() -> None:
    out = insert_page_markers(["p1", "p2", "p3"])
    assert out == "p1\n<!-- page 2 -->\np2\n<!-- page 3 -->\np3"


def test_insert_page_markers_preserves_content() -> None:
    pages = ["first content\n", "second content\n", "third content\n"]
    out = insert_page_markers(pages)
    assert "first content" in out
    assert "second content" in out
    assert "third content" in out


def test_insert_page_markers_custom_template() -> None:
    out = insert_page_markers(["a", "b"], template="[p={n}]")
    assert out == "a\n[p=2]\nb"


def test_split_by_page_markers_roundtrip() -> None:
    pages = ["alpha", "beta", "gamma"]
    out = insert_page_markers(pages)
    parts = split_by_page_markers(out)
    assert parts == pages


def test_split_by_page_markers_empty_first_segment() -> None:
    out = "<!-- page 2 -->resto"
    parts = split_by_page_markers(out)
    assert parts == ["", "resto"]


def test_split_by_page_markers_no_markers_returns_singleton() -> None:
    assert split_by_page_markers("plain text") == ["plain text"]


def test_split_by_page_markers_empty_string() -> None:
    assert split_by_page_markers("") == [""]


def test_strip_page_markers_removes_all() -> None:
    text = "before\n<!-- page 2 -->middle\n<!-- page 3 -->after"
    out = strip_page_markers(text)
    assert "<!-- page" not in out
    assert "before" in out
    assert "middle" in out
    assert "after" in out


def test_strip_page_markers_empty() -> None:
    assert strip_page_markers("") == ""


def test_strip_page_markers_no_markers_is_noop() -> None:
    assert strip_page_markers("plain") == "plain"


def test_join_pages_simple() -> None:
    assert join_pages(["a", "b", "c"]) == "a\nb\nc"


def test_join_pages_empty_list() -> None:
    assert join_pages([]) == ""


def test_page_marker_regex_matches_format() -> None:
    m = PAGE_MARKER_RE.match("<!-- page 42 -->")
    assert m is not None
    assert m.group(1) == "42"


def test_page_marker_regex_finds_in_text() -> None:
    text = "before <!-- page 7 --> middle <!-- page 8 --> end"
    matches = list(PAGE_MARKER_RE.finditer(text))
    assert [m.group(1) for m in matches] == ["7", "8"]


def test_page_marker_template_format() -> None:
    assert PAGE_MARKER_TEMPLATE.format(n=5) == "<!-- page 5 -->"


@pytest.mark.parametrize("n", [1, 2, 10, 99, 1000])
def test_insert_split_roundtrip_various_page_counts(n: int) -> None:
    pages = [f"content-{i}" for i in range(1, n + 1)]
    out = insert_page_markers(pages)
    parts = split_by_page_markers(out)
    assert parts == pages
