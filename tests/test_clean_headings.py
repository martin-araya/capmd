"""Tests del reconstructor de headings (D7)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    HeadingOptions,
    HeadingReconstructor,
    Pipeline,
    detect_heading_level,
    reconstruct_headings,
)
from capmd.clean.headings import (
    DEFAULT_NAME,
    DEFAULT_OPTIONS,
    RE_H1_ALLCAPS,
    RE_H1_CHAPTER,
    RE_H2_NUMBERED,
    RE_H3_NUMBERED,
)
from capmd.convert import Engine, insert_page_markers
from capmd.models import SourceDoc
from tests.fixtures import build


def _make_source(tmp_path: Path) -> SourceDoc:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return SourceDoc(
        path=p,
        format="pdf",
        sha256="0" * 64,
        size_bytes=p.stat().st_size,
    )


def _ctx(tmp_path: Path, **kwargs: object) -> CleanContext:
    return CleanContext(source=_make_source(tmp_path), format="pdf", **kwargs)


# --- Regex export ---


def test_regex_constants_compiled() -> None:
    assert RE_H1_CHAPTER.pattern
    assert RE_H1_ALLCAPS.pattern
    assert RE_H2_NUMBERED.pattern
    assert RE_H3_NUMBERED.pattern


# --- detect_heading_level (regex) ---


def test_detect_chapter_h1() -> None:
    assert detect_heading_level("Chapter 1: Introduction") == 1


def test_detect_capitulo_h1() -> None:
    assert detect_heading_level("Capítulo 3: Ownership") == 1


def test_detect_cap_h1() -> None:
    assert detect_heading_level("Cap. 1: Foo") == 1


def test_detect_h2_numbered() -> None:
    assert detect_heading_level("1.1 Background") == 2


def test_detect_h3_numbered_precedence() -> None:
    """H3 (X.Y.Z) debe matchear ANTES que H2 (X.Y)."""
    assert detect_heading_level("1.1.1 Details") == 3


def test_detect_allcaps_h1() -> None:
    assert detect_heading_level("BACKGROUND") == 1


def test_no_heading_short_caps() -> None:
    """\"OK\" de 2 chars no matchea ALL CAPS (mínimo 3)."""
    assert detect_heading_level("OK") == 0


def test_no_heading_long_line() -> None:
    long = "Lorem ipsum dolor sit amet " * 10  # >200 chars
    assert detect_heading_level(long) == 0


def test_no_heading_already_marked() -> None:
    assert detect_heading_level("# Title") == 0
    assert detect_heading_level("## Subtitle") == 0


def test_no_heading_empty_line() -> None:
    assert detect_heading_level("") == 0
    assert detect_heading_level("   ") == 0


def test_no_heading_regular_text() -> None:
    assert detect_heading_level("This is body text.") == 0


def test_no_heading_numbered_list_item() -> None:
    """`1. foo` no es H2 (necesita `X.Y`)."""
    assert detect_heading_level("1. foo") == 0


def test_no_heading_only_dots() -> None:
    assert detect_heading_level("1.1") == 0
    assert detect_heading_level("1.1.1") == 0


# --- detect_heading_level (font-size) ---


def test_detect_font_size_h1() -> None:
    assert detect_heading_level("Foo", font_size=17.0, body_median=10.0) == 1


def test_detect_font_size_h2() -> None:
    assert detect_heading_level("Foo", font_size=14.0, body_median=10.0) == 2


def test_detect_font_size_h3() -> None:
    assert detect_heading_level("Foo", font_size=12.0, body_median=10.0) == 3


def test_detect_font_size_h4() -> None:
    assert detect_heading_level("Foo", font_size=10.6, body_median=10.0) == 4


def test_no_heading_at_body_size() -> None:
    assert detect_heading_level("Foo", font_size=10.0, body_median=10.0) == 0


def test_no_heading_below_h4_threshold() -> None:
    assert detect_heading_level("Foo", font_size=10.04, body_median=10.0) == 0


def test_font_size_zero_body_median_falls_back_to_regex() -> None:
    assert detect_heading_level("Chapter 1", font_size=14.0, body_median=0.0) == 1


def test_font_size_overrides_regex_when_more_specific() -> None:
    """\"1.1 Foo\" matchea regex H2; con font ratio 2.0 debe ser H1."""
    assert detect_heading_level("1.1 Foo", font_size=20.0, body_median=10.0) == 1


def test_font_size_zero_falls_back_to_regex() -> None:
    assert detect_heading_level("Chapter 1", font_size=10.0, body_median=10.0) == 1


def test_detect_respects_min_max_length() -> None:
    opts = HeadingOptions(min_length=10, max_length=50)
    assert detect_heading_level("Chapter 1", options=opts) == 0
    assert detect_heading_level("Chapter 1: Long enough title", options=opts) == 1


# --- reconstruct_headings ---


def test_reconstruct_with_regex_only_chapter() -> None:
    out = reconstruct_headings("Chapter 1: Foo\nBody.")
    assert "# Chapter 1: Foo" in out


def test_reconstruct_with_regex_only_h2() -> None:
    out = reconstruct_headings("1.1 Background\nBody text.")
    assert "## 1.1 Background" in out


def test_reconstruct_with_regex_only_h3() -> None:
    out = reconstruct_headings("1.1.1 Details\nBody text.")
    assert "### 1.1.1 Details" in out


def test_reconstruct_adds_blank_before_heading() -> None:
    out = reconstruct_headings("Body line\n# Chapter 1\nMore body")
    assert out.startswith("\n# Chapter 1") or "\n\n# Chapter 1" in out or out.split("\n")[0] == ""


def test_reconstruct_no_blank_before_when_already_blank() -> None:
    out = reconstruct_headings("Body\n\n# Chapter 1")
    assert "\n\n\n# Chapter 1" not in out


def test_reconstruct_preserves_existing_headings() -> None:
    src = "# Already Heading\nBody."
    assert reconstruct_headings(src) == src


def test_reconstruct_handles_empty_text() -> None:
    assert reconstruct_headings("") == ""


def test_reconstruct_handles_no_headings() -> None:
    src = "Just some regular text.\nMore text."
    assert reconstruct_headings(src) == src


def test_reconstruct_with_page_font_sizes_basic() -> None:
    """Una página con dos líneas: la primera tiene font grande."""
    pages = ["BIG TITLE\nBody text in smaller font"]
    md = insert_page_markers(pages)
    page_font_sizes = (
        (30.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0),
    )
    out = reconstruct_headings(md, page_font_sizes=page_font_sizes)
    assert "# BIG TITLE" in out
    assert "Body text" in out


def test_reconstruct_with_page_font_sizes_no_change_when_uniform() -> None:
    pages = ["Body\nBody\nBody"]
    md = insert_page_markers(pages)
    page_font_sizes = ((10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0),)
    out = reconstruct_headings(md, page_font_sizes=page_font_sizes)
    assert out == md


def test_reconstruct_blank_line_before_disabled() -> None:
    opts = HeadingOptions(blank_line_before=False)
    out = reconstruct_headings("Body\n# Chapter 1", options=opts)
    assert "# Chapter 1\nMore" not in out
    assert out.startswith("Body\n# Chapter 1") or "Body\n# Chapter 1" in out


# --- HeadingReconstructor ---


def test_heading_reconstructor_default_name() -> None:
    assert HeadingReconstructor().name == DEFAULT_NAME
    assert DEFAULT_NAME == "headings"


def test_heading_reconstructor_pipeline_integration(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(HeadingReconstructor(),))
    md = "Chapter 1: Foo\nBody.\n1.1 Details\nMore."
    text, stats = pipeline.run(md, _ctx(tmp_path))
    assert "# Chapter 1: Foo" in text
    assert "## 1.1 Details" in text
    assert len(stats) == 1
    assert stats[0].name == "headings"
    assert stats[0].changes >= 2


def test_heading_reconstructor_reports_count(tmp_path: Path) -> None:
    md = "Chapter 1: Foo\n1.1 Bar\n1.1.1 Baz\nBody."
    text, stats = Pipeline(cleaners=(HeadingReconstructor(),)).run(md, _ctx(tmp_path))
    assert "# Chapter 1: Foo" in text
    assert "## 1.1 Bar" in text
    assert "### 1.1.1 Baz" in text
    assert stats[0].changes == 3


def test_heading_reconstructor_disabled(tmp_path: Path) -> None:
    md = "Chapter 1: Foo\nBody."
    pipeline = Pipeline(cleaners=(HeadingReconstructor(enabled=False),))
    text, stats = pipeline.run(md, _ctx(tmp_path))
    assert text == md
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_heading_reconstructor_empty_input(tmp_path: Path) -> None:
    result = HeadingReconstructor().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_heading_reconstructor_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(HeadingReconstructor(), Cleaner)


def test_heading_reconstructor_uses_page_font_sizes_from_context(tmp_path: Path) -> None:
    """Si CleanContext trae page_font_sizes, el cleaner los usa."""
    md = "BIG TITLE\nSmall body."
    page_font_sizes = ((40.0, 10.0),)
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf", page_font_sizes=page_font_sizes)
    result = HeadingReconstructor().run(md, ctx)
    assert "# BIG TITLE" in result.text
    assert result.changes >= 1


# --- CleanContext.page_font_sizes ---


def test_clean_context_page_font_sizes_default_none(tmp_path: Path) -> None:
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf")
    assert ctx.page_font_sizes is None


def test_clean_context_page_font_sizes_accepts_tuple(tmp_path: Path) -> None:
    sizes = ((10.0, 12.0), (10.0, 12.0, 14.0))
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf", page_font_sizes=sizes)
    assert ctx.page_font_sizes == sizes


def test_clean_context_is_frozen_with_page_font_sizes(tmp_path: Path) -> None:
    ctx = CleanContext(
        source=_make_source(tmp_path),
        format="pdf",
        page_font_sizes=((10.0,),),
    )
    with pytest.raises(FrozenInstanceError):
        ctx.page_font_sizes = None


# --- Fixture end-to-end (literal del roadmap) ---


def test_reconstruct_from_headings_fixture(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    pages = Engine().convert_pages(pdf)
    md = insert_page_markers(pages)
    out = reconstruct_headings(md)

    assert "# Chapter 1: Introduction" in out
    assert "## 1.1 Background" in out
    assert "### 1.1.1 Details" in out
    assert "# Chapter 2: Ownership" in out
    assert "## 2.1 Borrowing" in out


def test_headings_cleaner_with_fixture_via_pipeline(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    pages = Engine().convert_pages(pdf)
    md = insert_page_markers(pages)
    text, stats = Pipeline(cleaners=(HeadingReconstructor(),)).run(md, _ctx(tmp_path))

    assert "# Chapter 1: Introduction" in text
    assert "## 1.1 Background" in text
    assert "### 1.1.1 Details" in text
    assert "# Chapter 2: Ownership" in text
    assert stats[0].changes >= 5


def test_default_options_is_heading_options() -> None:
    assert isinstance(DEFAULT_OPTIONS, HeadingOptions)
