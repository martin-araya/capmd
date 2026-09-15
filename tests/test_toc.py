"""Tests unitarios de ``capmd.output.toc`` (F5)."""

from __future__ import annotations

import re

import pytest

from capmd.output.toc import (
    TOC_SENTINEL_CLOSE,
    TOC_SENTINEL_OPEN,
    Heading,
    build_toc_block,
    extract_headings,
    inject_toc,
    markdown_anchor,
    slugify_anchor,
)

# --- markdown_anchor ------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Hello World", "hello-world"),
        ("hello world", "hello-world"),
        ("Hello  World", "hello-world"),
        ("Hello-World", "hello-world"),
        ("  Hello World  ", "hello-world"),
        ("Mi Título", "mi-título"),
        ("Programación en Rust", "programación-en-rust"),
        ("What's up?", "what-s-up"),
        ('"Quotes" & ampersand', "quotes-ampersand"),
        ("Symbols !@#", "symbols"),
        ("", "untitled"),
        ("!!!", "untitled"),
        ("only---dashes", "only-dashes"),
        ("under_score", "under_score"),
        ("a/b\\c", "a-b-c"),
        ("Section 1.1", "section-1-1"),
        ("日本語", "日本語"),  # CJK se conserva literal
        ("Cyrillic тест", "cyrillic-тест"),
    ],
)
def test_markdown_anchor(title: str, expected: str) -> None:
    assert markdown_anchor(title) == expected


# --- slugify_anchor (dedup) ----------------------------------------------


def test_slugify_anchor_unique_first_use() -> None:
    used: set[str] = set()
    assert slugify_anchor("Hello World", used) == "hello-world"
    assert used == {"hello-world"}


def test_slugify_anchor_dedup_collisions() -> None:
    used: set[str] = set()
    assert slugify_anchor("Section", used) == "section"
    assert slugify_anchor("Section", used) == "section-1"
    assert slugify_anchor("Section", used) == "section-2"
    assert slugify_anchor("Other", used) == "other"
    assert used == {"section", "section-1", "section-2", "other"}


def test_slugify_anchor_emoji_only_falls_back() -> None:
    used: set[str] = set()
    # Anchor: emoji are stripped → empty → "untitled".
    assert slugify_anchor("🎉🎉", used) == "untitled"
    assert slugify_anchor("🎉🎉", used) == "untitled-1"


# --- extract_headings ------------------------------------------------------


def test_extract_basic_h2_and_h3() -> None:
    md = "# Title\n\n## Section A\nbody\n\n### Sub A1\nbody\n"
    headings = extract_headings(md)
    assert [h.level for h in headings] == [2, 3]
    assert [h.title for h in headings] == ["Section A", "Sub A1"]
    assert [h.anchor for h in headings] == ["section-a", "sub-a1"]


def test_extract_excludes_h1_by_default() -> None:
    md = "# Title\n\n## Section\nbody"
    headings = extract_headings(md)
    assert all(h.level >= 2 for h in headings)
    assert len(headings) == 1


def test_extract_includes_h1_when_min_level_1() -> None:
    md = "# Title\n\n## Section\nbody"
    headings = extract_headings(md, min_level=1, max_level=3)
    assert [h.level for h in headings] == [1, 2]


def test_extract_max_level_filters_out_deeper() -> None:
    md = "# Title\n\n## Section\nbody\n\n#### Deep\nbody\n"
    headings = extract_headings(md, max_level=3)
    assert [h.level for h in headings] == [2]


def test_extract_ignores_code_fences() -> None:
    md = (
        "# Title\n"
        "## Real\n"
        "body\n"
        "\n"
        "```python\n"
        "## This is inside code\n"
        "still inside\n"
        "```\n"
        "\n"
        "## Another\n"
        "body\n"
    )
    headings = extract_headings(md)
    assert [h.title for h in headings] == ["Real", "Another"]


def test_extract_ignores_tilde_fence() -> None:
    md = "# T\n~~~\n## Inside\n~~~\n## Outside\n"
    headings = extract_headings(md)
    assert [h.title for h in headings] == ["Outside"]


def test_extract_strips_existing_front_matter() -> None:
    """Los `##` dentro del FM inicial no se cuentan como headings."""
    md = (
        "---\n"
        "## No es sección\n"
        "title: x\n"
        "---\n"
        "\n"
        "## Real\n"
        "body\n"
    )
    headings = extract_headings(md)
    assert [h.title for h in headings] == ["Real"]


def test_extract_ignores_empty_headings() -> None:
    md = "# T\n\n## \nbody\n\n## Real\nbody\n"
    headings = extract_headings(md)
    assert [h.title for h in headings] == ["Real"]


def test_extract_dedup_anchors() -> None:
    md = "## Section\n1\n\n## Section\n2\n\n## Section\n3\n"
    headings = extract_headings(md)
    assert [h.anchor for h in headings] == ["section", "section-1", "section-2"]


def test_extract_empty_input() -> None:
    assert extract_headings("") == []


# --- build_toc_block ------------------------------------------------------


def test_build_toc_block_empty() -> None:
    assert build_toc_block([]) == ""


def test_build_toc_block_with_sentinels() -> None:
    headings = [Heading(level=2, title="A", anchor="a")]
    out = build_toc_block(headings)
    assert TOC_SENTINEL_OPEN in out
    assert TOC_SENTINEL_CLOSE in out
    assert out.startswith(TOC_SENTINEL_OPEN + "\n")
    assert out.endswith(TOC_SENTINEL_CLOSE + "\n")


def test_build_toc_block_format() -> None:
    headings = [
        Heading(level=2, title="A", anchor="a"),
        Heading(level=3, title="A1", anchor="a1"),
        Heading(level=4, title="A1a", anchor="a1a"),
    ]
    out = build_toc_block(headings)
    assert "- [A](#a)" in out
    assert "  - [A1](#a1)" in out
    assert "    - [A1a](#a1a)" in out


def test_build_toc_block_escapes_brackets() -> None:
    headings = [Heading(level=2, title="With [brackets]", anchor="with-brackets")]
    out = build_toc_block(headings)
    assert r"With \[brackets\]" in out


# --- inject_toc: insertion ------------------------------------------------


def test_inject_after_first_h1() -> None:
    md = "# Title\n\nintro\n\n## Section\nbody\n"
    out = inject_toc(md)
    h1_pos = out.index("# Title")
    toc_pos = out.index("<!-- capmd:toc:open -->")
    sec_pos = out.index("## Section")
    assert h1_pos < toc_pos < sec_pos


def test_inject_at_top_when_no_h1() -> None:
    md = "## Section\nbody\n"
    out = inject_toc(md)
    assert out.startswith("<!-- capmd:toc:open -->")
    assert "## Section" in out


def test_inject_with_front_matter_present() -> None:
    md = "---\ntitle: x\n---\n\n# Title\n\n## Section\nbody\n"
    out = inject_toc(md)
    fm_pos = out.index("---")  # opening of FM
    h1_pos = out.index("# Title")
    toc_pos = out.index("<!-- capmd:toc:open -->")
    assert fm_pos < h1_pos < toc_pos


def test_inject_no_headings_returns_unchanged() -> None:
    md = "# Title\n\njust text, no sections"
    out = inject_toc(md)
    assert out == md


def test_inject_strips_previous_toc() -> None:
    """Re-inject reemplaza el TOC previo, no acumula."""
    md = "# T\n\n## A\nbody\n"
    first = inject_toc(md)
    second = inject_toc(first)
    assert first == second
    # Solo UN set de sentinels en el output.
    assert second.count(TOC_SENTINEL_OPEN) == 1
    assert second.count(TOC_SENTINEL_CLOSE) == 1


def test_inject_depth_2_only_h2() -> None:
    md = "# T\n\n## A\nbody\n\n### A1\nbody\n"
    out = inject_toc(md, depth=2)
    # H2 sí; H3 no (ni en la lista de TOC ni como link).
    assert "- [A](#a)" in out
    assert "- [A1]" not in out
    # El heading H3 sigue en el body (no tocamos el cuerpo).
    assert "### A1" in out


def test_inject_depth_4_includes_h4() -> None:
    md = "# T\n\n## A\nbody\n\n### A1\nbody\n\n#### A1a\nbody"
    out = inject_toc(md, depth=4)
    assert "a1a" in out


def test_inject_section_anchors_resolve_to_real_headings() -> None:
    """Cada anchor de la TOC existe como heading en el doc."""
    md = "# Title\n\n## Section A\nbody\n\n## Section B\nbody\n"
    out = inject_toc(md)
    # Extraer anchors de la TOC
    toc_anchors = re.findall(r"\]\(#([^)]+)\)", out)
    # Extraer headings reales del markdown
    real_anchors = {h.anchor for h in extract_headings(md)}
    assert set(toc_anchors) <= real_anchors
    assert len(toc_anchors) >= 2


def test_inject_empty_markdown() -> None:
    assert inject_toc("") == ""


def test_inject_preserves_body_verbatim() -> None:
    md = "# T\n\n## A\nbody\n\n## B\nbody2\n"
    out = inject_toc(md)
    assert "## A\nbody\n" in out
    assert "## B\nbody2\n" in out
