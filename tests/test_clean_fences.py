"""Tests del helper de segmentación por fences."""

from __future__ import annotations

from capmd.clean._fences import (
    FENCE_LINE_RE,
    apply_outside_fences,
    split_outside_fences,
)


def test_split_no_fence_returns_single_outside_segment() -> None:
    text = "line one\nline two\n"
    segs = split_outside_fences(text)
    assert segs == [(text, False)]


def test_split_single_fence_returns_outside_then_inside_then_outside() -> None:
    text = "before\n```\ninside\n```\nafter\n"
    segs = split_outside_fences(text)
    assert len(segs) == 3
    assert segs[0] == ("before\n", False)
    assert segs[1][1] is True
    assert "inside" in segs[1][0]
    assert segs[2] == ("after\n", False)


def test_split_tilde_fence_also_detected() -> None:
    text = "before\n~~~\ninside\n~~~\nafter\n"
    segs = split_outside_fences(text)
    assert len(segs) == 3
    assert segs[1][1] is True


def test_split_fence_backticks_does_not_close_tilde() -> None:
    """``` no cierra un fence abierto con ~~~."""
    text = "before\n~~~\nstill inside ```\n~~~\nafter\n"
    segs = split_outside_fences(text)
    assert len(segs) == 3
    assert segs[1][1] is True
    assert "still inside" in segs[1][0]


def test_split_fence_tildes_does_not_close_backticks() -> None:
    text = "before\n```\nstill inside ~~~\n```\nafter\n"
    segs = split_outside_fences(text)
    assert len(segs) == 3
    assert segs[1][1] is True


def test_split_unclosed_fence_eats_rest() -> None:
    text = "before\n```\ninside forever\nmore inside"
    segs = split_outside_fences(text)
    assert len(segs) == 2
    assert segs[0] == ("before\n", False)
    assert segs[1][1] is True


def test_split_fence_with_indentation_prefix() -> None:
    text = "before\n   ```python\ninside\n   ```\nafter"
    segs = split_outside_fences(text)
    assert len(segs) == 3
    assert segs[1][1] is True


def test_apply_outside_fences_preserves_fence_content() -> None:
    text = "  before  \n```\n  inside  \n```\n  after  \n"
    out = apply_outside_fences(text, lambda s: s.replace("  ", ""))
    assert "  inside  " in out
    assert "before" in out and "  before" not in out


def test_apply_outside_fences_with_strip_callable() -> None:
    text = "  prose  \n```\n  code  \n```\n  more  "
    out = apply_outside_fences(text, str.strip)
    assert "  code  \n" in out
    assert out.startswith("prose")
    assert "more" in out


def test_split_empty_text() -> None:
    assert split_outside_fences("") == []


def test_apply_empty_text() -> None:
    assert apply_outside_fences("", lambda s: s.upper()) == ""


def test_split_multiple_fences() -> None:
    text = "A\n```\n1\n```\nB\n~~~\n2\n~~~\nC"
    segs = split_outside_fences(text)
    assert [s[1] for s in segs] == [False, True, False, True, False]


def test_fence_line_regex_matches() -> None:
    m = FENCE_LINE_RE.match("```python")
    assert m is not None
    assert m.group(2) == "```"
    m = FENCE_LINE_RE.match("~~~")
    assert m is not None
    assert m.group(2) == "~~~"


def test_fence_line_regex_rejects_text() -> None:
    assert FENCE_LINE_RE.match("just text") is None
    assert FENCE_LINE_RE.match("``not enough") is None
