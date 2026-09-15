"""Tests unitarios de ``capmd.output.frontmatter`` (F2)."""

from __future__ import annotations

import re

import pytest
import yaml

from capmd.output.frontmatter import (
    build_front_matter_fields,
    extract_first_h1,
    prepend_front_matter,
    render_front_matter,
    strip_existing_front_matter,
)

# --- extract_first_h1 ------------------------------------------------------


def test_extract_first_h1_simple() -> None:
    md = "# Hello World\n\nbody text"
    assert extract_first_h1(md) == "Hello World"


def test_extract_first_h1_with_blank_lines_before() -> None:
    md = "\n\n\n# Skipped blabla\n# Real One\n\nbody"
    assert extract_first_h1(md) == "Skipped blabla"


def test_extract_first_h1_does_not_match_h2() -> None:
    md = "## Subtitle\n\nbody"
    assert extract_first_h1(md) is None


def test_extract_first_h1_does_not_match_hash_without_space() -> None:
    md = "#hashtag\n\nbody"
    assert extract_first_h1(md) is None


def test_extract_first_h1_handles_h3_after_h1() -> None:
    md = "# Title\n\n## Section\n\n# Second H1"
    assert extract_first_h1(md) == "Title"


def test_extract_first_h1_empty() -> None:
    assert extract_first_h1("") is None
    assert extract_first_h1("just text\nno headings here") is None


def test_extract_first_h1_strips_trailing_whitespace() -> None:
    md = "# Title   \n\nbody"
    assert extract_first_h1(md) == "Title"


# --- strip_existing_front_matter -------------------------------------------


def test_strip_existing_front_matter_removes_block() -> None:
    md = "---\ntitle: Hi\n---\n\nbody text"
    assert strip_existing_front_matter(md) == "body text"


def test_strip_existing_front_matter_leaves_intact_when_absent() -> None:
    md = "# heading\n\nbody"
    assert strip_existing_front_matter(md) == md


def test_strip_existing_front_matter_preserves_leading_whitespace() -> None:
    md = "   \n---\ntitle: Hi\n---\n\nbody"
    stripped = strip_existing_front_matter(md)
    # Leading whitespace before the front matter is preserved.
    assert stripped == "   \nbody"


def test_strip_existing_front_matter_does_not_match_unclosed_block() -> None:
    md = "---\ntitle: Hi\nstill in fm\n\nbody"
    # No closing ---, so this is not a valid front matter; leave intact.
    assert strip_existing_front_matter(md) == md


def test_strip_existing_front_matter_only_at_start() -> None:
    """Un divider --- dentro del markdown no se considera front matter."""
    md = "some intro\n\n---\n\nmore text"
    assert strip_existing_front_matter(md) == md


# --- render_front_matter ---------------------------------------------------


def _make_fields() -> dict:
    return {
        "title": "Title",
        "book": "rust-handbook",
        "chapter": "cap-03-ownership",
        "pages": [45, 46, 47],
        "source_file": "Rust Handbook.pdf",
        "source_sha256": "abc",
        "converted_at": "2026-09-15T00:00:00Z",
        "capmd_version": "0.1.0",
        "markitdown_version": "0.1.7",
        "cleaners_applied": ["whitespace", "headers"],
    }


def test_render_front_matter_starts_with_triple_dash() -> None:
    rendered = render_front_matter(_make_fields())
    assert rendered.startswith("---\n")


def test_render_front_matter_ends_with_triple_dash_and_blank_line() -> None:
    rendered = render_front_matter(_make_fields())
    assert rendered.endswith("---\n\n")


def test_render_front_matter_parses_with_safe_load() -> None:
    rendered = render_front_matter(_make_fields())
    # Extract the YAML block between the first and last `---`
    inner_match = re.search(r"\A---\n(.*?)\n---\n", rendered, re.DOTALL)
    assert inner_match is not None
    parsed = yaml.safe_load(inner_match.group(1))
    assert parsed == _make_fields()


def test_render_front_matter_blocks_key_order() -> None:
    """El orden de claves en el YAML respeta el orden de inserción."""
    fields = _make_fields()
    rendered = render_front_matter(fields)
    # Localizar cada key en el orden esperado.
    positions = [rendered.index(f"\n{k}:") for k in fields]
    assert positions == sorted(positions)


def test_render_front_matter_escapes_colons_in_title() -> None:
    fields = _make_fields()
    fields["title"] = "Chapter: A Strange Title"
    rendered = render_front_matter(fields)
    # PyYAML debe haber quoteado el valor por el ``:``.
    parsed = re.search(r"\A---\n(.*?)\n---\n", rendered, re.DOTALL)
    assert parsed is not None
    loaded = yaml.safe_load(parsed.group(1))
    assert loaded["title"] == "Chapter: A Strange Title"


def test_render_front_matter_handles_none_as_null() -> None:
    fields = _make_fields()
    fields["pages"] = None
    fields["source_file"] = None
    rendered = render_front_matter(fields)
    parsed = re.search(r"\A---\n(.*?)\n---\n", rendered, re.DOTALL)
    assert parsed is not None
    loaded = yaml.safe_load(parsed.group(1))
    assert loaded["pages"] is None
    assert loaded["source_file"] is None


def test_render_front_matter_keeps_unicode() -> None:
    fields = _make_fields()
    fields["title"] = "Programación en Rust"
    rendered = render_front_matter(fields)
    assert "Programación" in rendered


# --- build_front_matter_fields --------------------------------------------


def test_build_front_matter_fields_order() -> None:
    fields = build_front_matter_fields(
        title="T",
        book_slug="b",
        chapter_slug="c",
        pages=None,
        source_file=None,
        source_sha256=None,
        converted_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0",
        cleaners_applied=(),
    )
    keys = list(fields.keys())
    assert keys == [
        "title", "book", "chapter", "pages", "source_file",
        "source_sha256", "converted_at", "capmd_version",
        "markitdown_version", "cleaners_applied",
    ]


def test_build_front_matter_fields_to_yaml_has_all_ten_keys() -> None:
    fields = build_front_matter_fields(
        title="Ownership",
        book_slug="rust-handbook",
        chapter_slug="cap-03-ownership",
        pages=[3],
        source_file="Rust Handbook.pdf",
        source_sha256="abc",
        converted_at="2026-09-15T00:00:00Z",
        capmd_version="0.1.0",
        cleaners_applied=("whitespace", "headers"),
    )
    rendered = render_front_matter(fields)
    parsed = yaml.safe_load(re.search(r"\A---\n(.*?)\n---\n", rendered, re.DOTALL).group(1))
    assert set(parsed.keys()) == {
        "title", "book", "chapter", "pages", "source_file",
        "source_sha256", "converted_at", "capmd_version",
        "markitdown_version", "cleaners_applied",
    }


# --- prepend_front_matter (idempotencia + composición) ----------------------


def test_prepend_front_matter_basic() -> None:
    md = "# Title\n\nbody"
    out = prepend_front_matter(md, _make_fields())
    assert out.startswith("---\n")
    # Después del bloque, viene el body sin front matter previo.
    assert out.endswith("body")


def test_prepend_front_matter_is_idempotent() -> None:
    """``prepend(prepend(md)) == prepend(md)`` (sin acumular YAML)."""
    md = "# Title\n\nbody"
    once = prepend_front_matter(md, _make_fields())
    twice = prepend_front_matter(once, _make_fields())
    assert twice == once


def test_prepend_front_matter_strips_existing_block() -> None:
    md = "---\ntitle: old\nchapter: old\n---\n\nbody\n"
    new = prepend_front_matter(md, _make_fields())
    # Solo un bloque `---` al principio.
    assert new.count("\n---\n") == 1 or new.count("\n---\n\n") == 1
    # El bloque final es el nuevo (no "old").
    parsed = re.search(r"\A---\n(.*?)\n---\n", new, re.DOTALL)
    assert parsed is not None
    loaded = yaml.safe_load(parsed.group(1))
    assert loaded["chapter"] == "cap-03-ownership"


@pytest.mark.parametrize(
    "title_input, expected",
    [
        ("plain text", "plain text"),
        ("with: colon", "with: colon"),
        ("Ownership", "Ownership"),
        ("Capítulo: Guía", "Capítulo: Guía"),
    ],
)
def test_render_handles_edge_titles(title_input: str, expected: str) -> None:
    fields = _make_fields()
    fields["title"] = title_input
    rendered = render_front_matter(fields)
    parsed = re.search(r"\A---\n(.*?)\n---\n", rendered, re.DOTALL)
    assert parsed is not None
    loaded = yaml.safe_load(parsed.group(1))
    assert loaded["title"] == expected
