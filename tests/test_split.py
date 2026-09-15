"""Tests unitarios de ``capmd.output.split`` (F4)."""

from __future__ import annotations

from capmd.output.split import (
    Section,
    build_index_markdown,
    extract_h2_sections,
    section_filename,
    split_section_filenames,
)

# --- extract_h2_sections: happy paths ---------------------------------------


def test_extract_basic_two_sections() -> None:
    md = (
        "## Introduction\n"
        "First body.\n"
        "\n"
        "## Borrowing\n"
        "Second body.\n"
    )
    out = extract_h2_sections(md)
    assert out.prelude == ""
    assert len(out.sections) == 2
    assert out.sections[0].title == "Introduction"
    assert out.sections[0].index == 1
    assert "First body" in out.sections[0].body
    assert out.sections[1].title == "Borrowing"
    assert out.sections[1].index == 2
    assert "Second body" in out.sections[1].body


def test_extract_with_prelude() -> None:
    md = (
        "Some intro text\n"
        "\n"
        "More intro.\n"
        "\n"
        "## Section A\n"
        "Body A.\n"
    )
    out = extract_h2_sections(md)
    # El preludio conserva el "\n" que separa el último párrafo del H2.
    assert out.prelude == "Some intro text\n\nMore intro.\n\n"
    assert len(out.sections) == 1
    assert out.sections[0].title == "Section A"
    # El body arranca después del "\n" de cierre del heading; incluye
    # el "\n" separador entre el H2 y la primera línea del body.
    assert "Body A." in out.sections[0].body


def test_extract_no_h2_returns_prelude_only() -> None:
    md = "Just text\nwith no headings\n"
    out = extract_h2_sections(md)
    # Sin H2, todo el input queda como preludio (sin strip).
    assert out.prelude == md
    assert out.sections == ()


def test_extract_empty_input() -> None:
    out = extract_h2_sections("")
    assert out.prelude == ""
    assert out.sections == ()


def test_extract_h2_at_start_no_prelude() -> None:
    md = "## First\nbody"
    out = extract_h2_sections(md)
    assert out.prelude == ""
    assert len(out.sections) == 1
    assert out.sections[0].title == "First"


def test_extract_three_sections_preserves_body_split() -> None:
    md = (
        "## Alpha\n"
        "A1\n\n"
        "## Beta\n"
        "B1\n\n"
        "## Gamma\n"
        "G1\n"
    )
    out = extract_h2_sections(md)
    assert len(out.sections) == 3
    assert out.sections[0].title == "Alpha"
    assert out.sections[1].title == "Beta"
    assert out.sections[2].title == "Gamma"
    assert "A1" in out.sections[0].body
    assert "B1" not in out.sections[0].body  # no overlap
    assert "B1" in out.sections[1].body
    assert "G1" in out.sections[2].body


# --- extract_h2_sections: edge cases / negative cases ----------------------


def test_extract_ignores_h3() -> None:
    md = "## H2 title\nbody\n\n### H3\nsub\n"
    out = extract_h2_sections(md)
    assert len(out.sections) == 1
    assert out.sections[0].title == "H2 title"
    assert "H3" in out.sections[0].body or "sub" in out.sections[0].body


def test_extract_ignores_hashtag_without_space() -> None:
    """`##hashtag` (sin espacio) no se cuenta como H2.

    ``## real`` mid-line NO se cuenta (markdown requiere ``##`` al inicio
    de línea); necesita empezar en su propia línea.
    """
    md = "##hashtag\nOther ## inline\n## Real\nbody\n"
    out = extract_h2_sections(md)
    titles = [s.title for s in out.sections]
    assert titles == ["Real"]
    # El "##hashtag" y "## inline" van como contenido del prelude o
    # del body de Real — no se cuentan como headings.
    joined = out.prelude + "".join(s.body for s in out.sections)
    assert "##hashtag" in joined
    assert "## inline" in joined


def test_extract_ignores_h2_inside_code_fence() -> None:
    md = (
        "## Real\n"
        "body\n"
        "\n"
        "```python\n"
        "## This is inside code\n"
        "still inside\n"
        "```\n"
        "\n"
        "## Another\n"
        "second body\n"
    )
    out = extract_h2_sections(md)
    titles = [s.title for s in out.sections]
    assert "Real" in titles
    assert "Another" in titles
    assert not any("This is inside" in t for t in titles)


def test_extract_ignores_h2_inside_tilde_fence() -> None:
    md = (
        "## Real\n"
        "body\n"
        "\n"
        "~~~python\n"
        "## Inside tildes\n"
        "~~~\n"
        "## After\n"
        "ok\n"
    )
    out = extract_h2_sections(md)
    titles = [s.title for s in out.sections]
    assert titles == ["Real", "After"]


def test_extract_unclosed_fence_handles_rest_gracefully() -> None:
    """Un fence sin cerrar deja todo el resto dentro del fence."""
    md = "## Real\nbody\n\n```\n## Inside unclosed\n"
    out = extract_h2_sections(md)
    titles = [s.title for s in out.sections]
    assert "Real" in titles
    assert not any("Inside unclosed" in t for t in titles)


def test_extract_strips_existing_front_matter() -> None:
    """El front matter no se cuenta como sección (los `##` del YAML no se splittean)."""
    md = (
        "---\n"
        "title: x\n"
        "## No es sección\n"
        "---\n"
        "\n"
        "## Real\n"
        "body\n"
    )
    out = extract_h2_sections(md)
    titles = [s.title for s in out.sections]
    assert titles == ["Real"]


def test_extract_strips_trailing_whitespace_in_title() -> None:
    md = "##   Spaced Title   \nbody\n"
    out = extract_h2_sections(md)
    assert out.sections[0].title == "Spaced Title"


# --- section_filename -----------------------------------------------------


def test_section_filename_two_digits() -> None:
    assert section_filename(1, 4, "Introduction") == "01-introduction.md"
    assert section_filename(9, 9, "Wrap-up") == "09-wrap-up.md"


def test_section_filename_three_digits_at_100() -> None:
    # 100 secciones → ancho 3 dígitos.
    assert section_filename(1, 100, "Intro") == "001-intro.md"
    assert section_filename(100, 100, "Last") == "100-last.md"


def test_section_filename_empty_slug_fallback() -> None:
    """Título que slugea a 'untitled' cae a 'section'."""
    assert section_filename(3, 5, "!!!") == "03-section.md"
    assert section_filename(1, 2, "") == "01-section.md"


def test_section_filename_caps_slug_length() -> None:
    long = "a" * 80
    out = section_filename(1, 2, long)
    # El nombre del archivo (sin el prefijo numérico + .md) no pasa de ~60 chars.
    assert len(out) < 80


# --- split_section_filenames -----------------------------------------------


def test_split_filenames_no_prelude() -> None:
    sections = (
        Section(title="A", body="x", index=1),
        Section(title="B", body="y", index=2),
    )
    files, intro = split_section_filenames(sections, has_prelude=False)
    assert intro is None
    assert files == ["01-a.md", "02-b.md"]


def test_split_filenames_with_prelude() -> None:
    sections = (
        Section(title="A", body="x", index=1),
        Section(title="B", body="y", index=2),
    )
    files, intro = split_section_filenames(sections, has_prelude=True)
    assert intro == "00-intro.md"
    assert files == ["01-a.md", "02-b.md"]


def test_split_filenames_dedup_slugs() -> None:
    sections = (
        Section(title="Intro", body="x", index=1),
        Section(title="Intro", body="y", index=2),
        Section(title="Intro", body="z", index=3),
    )
    files, _ = split_section_filenames(sections, has_prelude=False)
    assert files == ["01-intro.md", "02-intro-2.md", "03-intro-3.md"]


def test_split_filenames_total_dedup_zero_pad() -> None:
    """Con 100 secciones y prelude, el pad sube a 3."""
    sections = tuple(
        Section(title=f"S{i}", body="x", index=i + 1) for i in range(100)
    )
    files, intro = split_section_filenames(sections, has_prelude=True)
    assert intro == "000-intro.md"
    assert files[0] == "001-s0.md"
    assert files[-1] == "100-s99.md"


# --- build_index_markdown -------------------------------------------------


def test_build_index_with_chapter_title() -> None:
    sections = (
        Section(title="Introduction", body="x", index=1),
        Section(title="Borrowing", body="y", index=2),
    )
    out = build_index_markdown(
        "Chapter 2",
        sections,
        ["01-introduction.md", "02-borrowing.md"],
        intro_filename=None,
    )
    assert "# Chapter 2" in out
    assert "- [Introduction](01-introduction.md)" in out
    assert "- [Borrowing](02-borrowing.md)" in out


def test_build_index_no_chapter_title() -> None:
    sections = (Section(title="Solo", body="", index=1),)
    out = build_index_markdown("", sections, ["01-solo.md"], intro_filename=None)
    assert not out.startswith("#")
    assert "- [Solo](01-solo.md)" in out


def test_build_index_includes_intro_at_end_when_present() -> None:
    sections = (Section(title="Real", body="x", index=1),)
    out = build_index_markdown(
        "Title", sections, ["01-real.md"], intro_filename="00-intro.md"
    )
    # Real va antes, intro va al final.
    assert out.index("01-real.md") < out.index("00-intro.md")


def test_build_index_escapes_brackets_in_titles() -> None:
    sections = (Section(title="With [brackets]", body="", index=1),)
    out = build_index_markdown(
        "Title", sections, ["01-b.md"], intro_filename=None
    )
    assert r"With \[brackets\]" in out


# --- Round-trip: split + reassemble ---------------------------------------


def test_round_trip_body_reassembly() -> None:
    """El body reensamblado en orden preserva el contenido (con cortes H2)."""
    md = (
        "## A\n"
        "a-line\n"
        "## B\n"
        "b-line\n"
        "## C\n"
        "c-line\n"
    )
    out = extract_h2_sections(md)
    assert out.prelude == ""
    # Reconstruir: preludio vacío + cada body sin el heading.
    rebuilt = "".join(s.body for s in out.sections)
    assert "a-line" in rebuilt
    assert "b-line" in rebuilt
    assert "c-line" in rebuilt
    # Los headings NO se preservan en los bodies (se splitean).
    for h in ("## A", "## B", "## C"):
        assert h not in rebuilt
