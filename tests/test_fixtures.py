"""Tests que generan los 6 PDFs sintéticos en tmp_path (A6)."""

from __future__ import annotations

from pathlib import Path

from tests.fixtures import build


def test_headings_pdf(tmp_path: Path) -> None:
    p = build.build_headings_pdf(tmp_path / "headings.pdf")
    assert p.exists() and p.stat().st_size > 0


def test_header_footer_pdf(tmp_path: Path) -> None:
    p = build.build_header_footer_pdf(tmp_path / "header_footer.pdf")
    assert p.exists() and p.stat().st_size > 0


def test_cut_hyphens_pdf(tmp_path: Path) -> None:
    p = build.build_cut_hyphens_pdf(tmp_path / "cut_hyphens.pdf")
    assert p.exists() and p.stat().st_size > 0


def test_two_images_pdf(tmp_path: Path) -> None:
    work = tmp_path / "_imgs"
    p = build.build_two_images_pdf(tmp_path / "two_images.pdf", work)
    assert p.exists() and p.stat().st_size > 0


def test_table_pdf(tmp_path: Path) -> None:
    p = build.build_table_pdf(tmp_path / "table.pdf")
    assert p.exists() and p.stat().st_size > 0


def test_outline_toc_pdf(tmp_path: Path) -> None:
    p = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    assert p.exists() and p.stat().st_size > 0


def test_all_six_fixtures_in_one_tmp_path(tmp_path: Path) -> None:
    """Test literal del roadmap: pytest genera los 6 PDFs en tmp_path."""
    work = tmp_path / "_imgs"
    paths = [
        build.build_headings_pdf(tmp_path / "headings.pdf"),
        build.build_header_footer_pdf(tmp_path / "header_footer.pdf"),
        build.build_cut_hyphens_pdf(tmp_path / "cut_hyphens.pdf"),
        build.build_two_images_pdf(tmp_path / "two_images.pdf", work),
        build.build_table_pdf(tmp_path / "table.pdf"),
        build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf"),
    ]
    assert len(paths) == 6
    for p in paths:
        assert p.exists() and p.stat().st_size > 0 and p.suffix == ".pdf"
