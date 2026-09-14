"""Tests de la tabla de formatos (B2, C9)."""

from __future__ import annotations

from capmd.convert.formats import SUPPORTED_FORMATS, known_extensions


def test_supported_formats_has_six_entries() -> None:
    assert len(SUPPORTED_FORMATS) == 6


def test_known_extensions_is_sorted_and_stripped() -> None:
    assert known_extensions() == ["docx", "epub", "html", "pdf", "pptx", "xlsx"]


def test_pdf_requires_pdf_extra() -> None:
    pdf = SUPPORTED_FORMATS[".pdf"]
    assert pdf.extra == "pdf"
    assert pdf.sentinel == "pdfminer.high_level"


def test_epub_has_no_extra() -> None:
    epub = SUPPORTED_FORMATS[".epub"]
    assert epub.extra is None
    assert epub.sentinel == ""


def test_html_has_no_extra() -> None:
    """HTML es interno al slice de capítulos EPUB; no requiere extra."""
    html = SUPPORTED_FORMATS[".html"]
    assert html.extra is None
    assert html.sentinel == ""


def test_install_hint_for_pdf() -> None:
    assert "pip install 'markitdown[pdf]'" in SUPPORTED_FORMATS[".pdf"].install_hint()
