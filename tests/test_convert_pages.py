"""Tests de ``Engine.convert_pages`` (D5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.convert.engine import Engine
from capmd.errors import SourceNotFound, UnsupportedFormat
from tests.fixtures import build


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    return build.build_header_footer_pdf(tmp_path / "header_footer.pdf")


@pytest.fixture
def engine() -> Engine:
    return Engine()


def test_convert_pages_returns_one_per_page(engine: Engine, pdf_path: Path) -> None:
    pages = engine.convert_pages(pdf_path)
    assert len(pages) == 4
    assert all(isinstance(p, str) for p in pages)


def test_convert_pages_each_page_has_section_heading(engine: Engine, pdf_path: Path) -> None:
    pages = engine.convert_pages(pdf_path)
    assert "Section A" in pages[0]
    assert "Section B" in pages[1]
    assert "Section C" in pages[2]
    assert "Section D" in pages[3]


def test_convert_pages_missing_file_raises(engine: Engine, tmp_path: Path) -> None:
    missing = tmp_path / "nope.pdf"
    with pytest.raises(SourceNotFound):
        engine.convert_pages(missing)


def test_convert_pages_non_pdf_raises(tmp_path: Path) -> None:
    txt = tmp_path / "not_pdf.txt"
    txt.write_text("hello")
    engine = Engine()
    with pytest.raises(UnsupportedFormat):
        engine.convert_pages(txt)


def test_convert_pages_uses_size_limits(engine: Engine, tmp_path: Path) -> None:
    from capmd.convert.limits import ConversionLimits
    from capmd.errors import InputTooLarge

    tight = ConversionLimits(max_size_bytes=10)
    p = build.build_header_footer_pdf(tmp_path / "big.pdf")
    with pytest.raises(InputTooLarge):
        engine.convert_pages(p, limits=tight)


def test_convert_pages_rejects_docx(tmp_path: Path) -> None:
    docx_path = tmp_path / "fake.docx"
    docx_path.write_bytes(b"PK\x03\x04fake-docx-bytes")
    engine = Engine()
    with pytest.raises(UnsupportedFormat):
        engine.convert_pages(docx_path)
