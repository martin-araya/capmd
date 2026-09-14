"""Tests de :func:`capmd.sources.pdf.slice_pdf` (fase C4).

Cubre: el temporal tiene solo las páginas pedidas, preserva el orden,
maneja PDFs corruptos y acepta ``PageRange`` con una sola página.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from capmd.errors import SourceNotFound
from capmd.models import PageRange
from capmd.sources.pdf import slice_pdf
from tests.fixtures import build


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")


def test_slice_returns_pdf_with_only_selected_pages(tmp_path: Path) -> None:
    src = _outline_pdf(tmp_path)
    out = slice_pdf(src, PageRange(pages=(2,)))
    try:
        reader = PdfReader(str(out))
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text() or ""
        # La página 2 del fixture arranca con "Chapter 2: Ownership".
        first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
        assert "Chapter 2" in first_line
    finally:
        out.unlink(missing_ok=True)


def test_slice_preserves_sorted_order(tmp_path: Path) -> None:
    """El output está en el orden de ``pages.pages`` (que PageRange garantiza sorted)."""
    src = _outline_pdf(tmp_path)
    out = slice_pdf(src, PageRange(pages=(1, 3)))
    try:
        reader = PdfReader(str(out))
        assert len(reader.pages) == 2
        first_line_p1 = next(
            (ln for ln in (reader.pages[0].extract_text() or "").splitlines() if ln.strip()),
            "",
        )
        first_line_p2 = next(
            (ln for ln in (reader.pages[1].extract_text() or "").splitlines() if ln.strip()),
            "",
        )
        # p1 del temporal = página 1 del original -> Ch1.
        # p2 del temporal = página 3 del original -> Ch3.
        assert "Chapter 1" in first_line_p1
        assert "Chapter 3" in first_line_p2
    finally:
        out.unlink(missing_ok=True)


def test_slice_cleanup_via_unlink(tmp_path: Path) -> None:
    """El cleanup queda al caller; ``unlink`` no debe fallar."""
    src = _outline_pdf(tmp_path)
    out = slice_pdf(src, PageRange(pages=(1,)))
    assert out.exists()
    out.unlink(missing_ok=True)
    assert not out.exists()
    # idempotente
    out.unlink(missing_ok=True)


def test_slice_corrupt_pdf_raises_source_not_found(tmp_path: Path) -> None:
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a real pdf")
    with pytest.raises(SourceNotFound):
        slice_pdf(bad, PageRange(pages=(1,)))


def test_slice_with_all_pages(tmp_path: Path) -> None:
    src = _outline_pdf(tmp_path)
    out = slice_pdf(src, PageRange(pages=(1, 2, 3)))
    try:
        reader = PdfReader(str(out))
        assert len(reader.pages) == 3
    finally:
        out.unlink(missing_ok=True)
