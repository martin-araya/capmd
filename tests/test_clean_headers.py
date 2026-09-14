"""Tests del cleaner de headers/footers (D4)."""

from __future__ import annotations

from pathlib import Path

from capmd.clean import (
    CleanContext,
    HeaderFooterCleaner,
    HeaderFooterOptions,
    Pipeline,
    detect_headers_footers,
    normalize_line,
    remove_headers_footers,
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


def _ctx(tmp_path: Path) -> CleanContext:
    return CleanContext(source=_make_source(tmp_path), format="pdf")


def _build_marked_with_headers() -> str:
    """Markdown sintético con 4 páginas y header/footer repetidos."""
    pages = [
        "Capítulo 3 | Rust in Action\nSection A\nBody A\n— 1 —\n",
        "Capítulo 3 | Rust in Action\nSection B\nBody B\n— 2 —\n",
        "Capítulo 3 | Rust in Action\nSection C\nBody C\n— 3 —\n",
        "Capítulo 3 | Rust in Action\nSection D\nBody D\n— 4 —\n",
    ]
    return insert_page_markers(pages)


# --- normalize_line ---


def test_normalize_line_strips_ends_and_collapses_whitespace() -> None:
    assert normalize_line("  foo   bar  ") == "foo bar"


def test_normalize_line_empty() -> None:
    assert normalize_line("") == ""
    assert normalize_line("   ") == ""


# --- detect_headers_footers ---


def test_detect_headers_footers_roadmap_case() -> None:
    pages = [
        "Capítulo 3 | Rust in Action\nSec A\nBody\n— 1 —",
        "Capítulo 3 | Rust in Action\nSec B\nBody\n— 2 —",
        "Capítulo 3 | Rust in Action\nSec C\nBody\n— 3 —",
        "Capítulo 3 | Rust in Action\nSec D\nBody\n— 4 —",
    ]
    headers, footers = detect_headers_footers(pages)
    assert "Capítulo 3 | Rust in Action" in headers
    # Footers con page numbers variables NO se detectan en MVP
    assert all(not f.startswith("—") for f in footers)


def test_detect_headers_footers_too_few_pages() -> None:
    pages = ["Header\nBody\nFooter"]
    headers, footers = detect_headers_footers(pages)
    assert headers == frozenset()
    assert footers == frozenset()


def test_detect_headers_footers_below_threshold() -> None:
    pages = [
        "Common Header\nPage 1 body",
        "Common Header\nPage 2 body",
        "Unique intro\nPage 3 body",
        "Common Header\nPage 4 body",
    ]
    headers, _footers = detect_headers_footers(pages)
    assert "Common Header" in headers
    assert "Unique intro" not in headers


# --- remove_headers_footers ---


def test_remove_headers_footers_removes_header() -> None:
    md = _build_marked_with_headers()
    out = remove_headers_footers(md)
    assert "Capítulo 3 | Rust in Action" not in out
    assert "Section A" in out
    assert "Section D" in out


def test_remove_headers_footers_zero_occurrences_roadmap() -> None:
    """Test literal del roadmap: 0 ocurrencias en el output."""
    md = _build_marked_with_headers()
    out = remove_headers_footers(md)
    assert out.count("Capítulo 3 | Rust in Action") == 0


def test_remove_headers_footers_strips_markers() -> None:
    md = _build_marked_with_headers()
    out = remove_headers_footers(md)
    assert "<!-- page" not in out


def test_remove_headers_footers_keeps_body_intact() -> None:
    md = _build_marked_with_headers()
    out = remove_headers_footers(md)
    for body in ("Body A", "Body B", "Body C", "Body D"):
        assert body in out


def test_remove_headers_footers_no_markers_is_noop() -> None:
    text = "plain markdown without any markers"
    assert remove_headers_footers(text) == text


def test_remove_headers_footers_handles_whitespace_variants() -> None:
    pages = [
        "Capítulo  3  |  Rust in Action\nSec A\nBody A",
        "Capítulo 3 | Rust in Action\nSec B\nBody B",
        "Capítulo 3 | Rust in Action\nSec C\nBody C",
        "Capítulo 3 | Rust in Action\nSec D\nBody D",
    ]
    md = insert_page_markers(pages)
    out = remove_headers_footers(md)
    assert "Capítulo 3 | Rust in Action" not in out
    assert "Capítulo" not in out


def test_remove_headers_footers_first_page_chapter_title_kept() -> None:
    """La primera página con chapter title aparece solo en 1/N (<60%)."""
    pages = [
        "Capítulo 3 | Rust in Action\nCapítulo 3: Ownership\nBody",
        "Capítulo 3 | Rust in Action\nBody B",
        "Capítulo 3 | Rust in Action\nBody C",
        "Capítulo 3 | Rust in Action\nBody D",
    ]
    md = insert_page_markers(pages)
    out = remove_headers_footers(md)
    assert "Capítulo 3 | Rust in Action" not in out
    assert "Capítulo 3: Ownership" in out


def test_remove_headers_footers_keep_markers_option() -> None:
    md = _build_marked_with_headers()
    opts = HeaderFooterOptions(keep_markers=True)
    out = remove_headers_footers(md, options=opts)
    assert "<!-- page" in out
    assert "Capítulo 3 | Rust in Action" not in out


# --- HeaderFooterCleaner ---


def test_header_footer_cleaner_default_name() -> None:
    from capmd.clean.headers import DEFAULT_NAME

    assert HeaderFooterCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "headers"


def test_header_footer_cleaner_pipeline_integration(tmp_path: Path) -> None:
    md = _build_marked_with_headers()
    pipeline = Pipeline(cleaners=(HeaderFooterCleaner(),))
    text, stats = pipeline.run(md, _ctx(tmp_path))

    assert "Capítulo 3 | Rust in Action" not in text
    assert "Section A" in text
    assert len(stats) == 1
    assert stats[0].name == "headers"
    assert stats[0].changes >= 1


def test_header_footer_cleaner_disabled(tmp_path: Path) -> None:
    md = _build_marked_with_headers()
    pipeline = Pipeline(cleaners=(HeaderFooterCleaner(enabled=False),))
    text, stats = pipeline.run(md, _ctx(tmp_path))
    assert text == md
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_header_footer_cleaner_no_markers_noop(tmp_path: Path) -> None:
    text = "plain text without markers"
    result = HeaderFooterCleaner().run(text, _ctx(tmp_path))
    assert result.text == text
    assert result.changes == 0


def test_header_footer_cleaner_changes_count(tmp_path: Path) -> None:
    md = _build_marked_with_headers()
    result = HeaderFooterCleaner().run(md, _ctx(tmp_path))
    assert result.changes == 1  # solo el header; footers no llegan al threshold


def test_header_footer_options_min_pages() -> None:
    opts = HeaderFooterOptions(min_pages=5)
    md = _build_marked_with_headers()  # 4 páginas
    result = HeaderFooterCleaner(options=opts).run(md, _ctx(Path("/tmp")))
    assert result.changes == 0


# --- Integración con fixture real (D5 + D4) ---


def test_end_to_end_with_real_fixture(tmp_path: Path) -> None:
    """D5 produce las páginas, D4 quita el header si aparece."""
    pdf = build.build_header_footer_pdf(tmp_path / "fixture.pdf")
    pages = Engine().convert_pages(pdf)
    assert len(pages) == 4
    md = insert_page_markers(pages)
    out = remove_headers_footers(md)
    assert "<!-- page" not in out
    # Section headings se preservan
    assert "Section A" in out
    assert "Section D" in out
