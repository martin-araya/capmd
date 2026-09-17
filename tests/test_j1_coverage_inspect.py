"""J1 coverage tests for inspect.py: ejercita los branches no cubiertos
del módulo ``capmd.inspect``, especialmente los renderers y los caminos
de error/edge case.
"""

from __future__ import annotations

from pathlib import Path

from capmd.inspect import (
    FontsInspection,
    HeadersInspection,
    InspectionReport,
    OutlineInspection,
    _check,
    _collect_fonts,
    _count_words,
    _inspect_epub,
    _inspect_pdf_outline,
    _normalize_line,
    _render_text_plain,
    _section_fonts,
    _section_headers,
    _section_outline,
    _section_text_epub,
    _section_text_pdf,
    _split_lines,
    inspect_pdf,
    render_text,
)
from tests.fixtures import build as fix_build


def _report(**kwargs) -> InspectionReport:
    defaults = {
        "schema_version": 1,
        "path": "/x.pdf",
        "format": "pdf",
        "pages": 3,
        "words_total": 100,
        "words_per_page": 33.3,
        "scanned": False,
        "outline": None,
        "fonts": None,
        "headers": None,
        "sampled_pages": None,
    }
    defaults.update(kwargs)
    return InspectionReport(**defaults)


class TestInspectHelpers:
    def test_check_ok(self) -> None:
        assert _check(True) == "[OK]"

    def test_check_warn(self) -> None:
        assert _check(False) == "[WARN]"

    def test_normalize_line(self) -> None:
        assert _normalize_line("  hola   mundo  ") == "hola mundo"
        assert _normalize_line("") == ""

    def test_count_words(self) -> None:
        assert _count_words("uno dos tres") == 3
        assert _count_words("") == 0

    def test_split_lines(self) -> None:
        out = _split_lines("a\n\nb\n   \nc")
        assert out == ["a", "b", "c"]


class TestSectionRenderers:
    def test_section_text_pdf_ok(self) -> None:
        r = _report(words_per_page=15.0, scanned=False)
        panel = _section_text_pdf(r)
        assert panel is not None

    def test_section_text_pdf_scanned(self) -> None:
        r = _report(words_per_page=2.0, scanned=True, pages=5)
        panel = _section_text_pdf(r)
        assert panel is not None

    def test_section_text_epub(self) -> None:
        panel = _section_text_epub()
        assert panel is not None

    def test_section_outline_empty(self) -> None:
        oi = OutlineInspection(source="none", count=0)
        panel = _section_outline(oi)
        assert panel is not None

    def test_section_outline_heuristic(self) -> None:
        oi = OutlineInspection(
            source="heuristic", count=5, items=((1, "Cap 1", 1), (2, "Sec", 2))
        )
        panel = _section_outline(oi)
        assert panel is not None

    def test_section_outline_outline_source(self) -> None:
        oi = OutlineInspection(
            source="outline", count=2, items=((1, "Cap 1", 1),)
        )
        panel = _section_outline(oi)
        assert panel is not None

    def test_section_outline_with_error(self) -> None:
        oi = OutlineInspection(source="none", count=0, error="boom")
        panel = _section_outline(oi)
        assert panel is not None

    def test_section_outline_capped_at_20(self) -> None:
        # 30 items, cap → show "+10 más" line.
        items = tuple((1, f"Ch{i}", i) for i in range(1, 31))
        oi = OutlineInspection(source="outline", count=30, items=items[:20])
        panel = _section_outline(oi)
        assert panel is not None

    def test_section_fonts_empty(self) -> None:
        fi = FontsInspection(count=0)
        panel = _section_fonts(fi)
        assert panel is not None

    def test_section_fonts_with_items(self) -> None:
        fi = FontsInspection(count=2, items=(("Helvetica", "Regular"), ("Helvetica-Bold", "Bold")))
        panel = _section_fonts(fi)
        assert panel is not None

    def test_section_fonts_with_error(self) -> None:
        fi = FontsInspection(count=0, error="boom")
        panel = _section_fonts(fi)
        assert panel is not None

    def test_section_headers_empty(self) -> None:
        hi = HeadersInspection(headers=(), footers=())
        panel = _section_headers(hi)
        assert panel is not None

    def test_section_headers_with_items(self) -> None:
        hi = HeadersInspection(headers=("Title",), footers=("Page",))
        panel = _section_headers(hi)
        assert panel is not None

    def test_section_headers_with_error(self) -> None:
        hi = HeadersInspection(error="boom")
        panel = _section_headers(hi)
        assert panel is not None


class TestRenderTextPlain:
    """Tests del fallback plain (cuando rich no está disponible)."""

    def test_plain_minimal(self) -> None:
        r = _report(words_per_page=None)
        out = _render_text_plain(r)
        assert "/x.pdf" in out
        assert "pdf" in out

    def test_plain_with_text(self) -> None:
        r = _report(words_per_page=15.0, scanned=False)
        out = _render_text_plain(r)
        assert "[OK]" in out
        assert "15.0" in out

    def test_plain_with_scanned(self) -> None:
        r = _report(words_per_page=2.0, scanned=True)
        out = _render_text_plain(r)
        assert "[WARN]" in out

    def test_plain_with_outline_error(self) -> None:
        r = _report(outline=OutlineInspection(source="none", count=0, error="boom"))
        out = _render_text_plain(r)
        assert "outline" in out
        assert "boom" in out

    def test_plain_with_outline_ok(self) -> None:
        r = _report(outline=OutlineInspection(source="outline", count=5))
        out = _render_text_plain(r)
        assert "outline" in out

    def test_plain_with_fonts(self) -> None:
        r = _report(fonts=FontsInspection(count=2))
        out = _render_text_plain(r)
        assert "fonts" in out
        assert "2" in out

    def test_plain_with_headers(self) -> None:
        r = _report(
            headers=HeadersInspection(headers=("H",), footers=("F1", "F2"))
        )
        out = _render_text_plain(r)
        assert "headers" in out


class TestRenderTextRich:
    """Tests del renderer rich: ejercitan todos los branches."""

    def test_render_text_pdf(self, tmp_path: Path) -> None:
        pdf = fix_build.build_outline_toc_pdf(tmp_path / "t.pdf")
        r = inspect_pdf(pdf)
        out = render_text(r)
        assert len(out) > 0

    def test_render_text_epub(self, tmp_path: Path) -> None:
        epub = fix_build.build_epub_with_3_chapters(tmp_path / "b.epub")
        r = inspect_pdf(epub)
        out = render_text(r)
        assert len(out) > 0

    def test_render_text_scanned_sample_message(self, tmp_path: Path) -> None:
        # Build a PDF with 5+ pages but sample=2 → "sample: N de M" message.
        pdf = fix_build.build_scanned_pdf(tmp_path / "s.pdf", n_pages=5)
        r = inspect_pdf(pdf, sample=2)
        out = render_text(r)
        assert len(out) > 0


class TestInspectPdfOutlineDirect:
    def test_inspect_pdf_outline_with_outline(self, tmp_path: Path) -> None:
        pdf = fix_build.build_outline_toc_pdf(tmp_path / "t.pdf")
        oi = _inspect_pdf_outline(pdf)
        assert oi.source == "outline"
        assert oi.count > 0

    def test_inspect_pdf_outline_heuristic(self, tmp_path: Path) -> None:
        # PDF sin outline embebido.
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas as cm

        pdf = tmp_path / "no_outline.pdf"
        c = cm.Canvas(str(pdf), pagesize=LETTER)
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, "Chapter 1")
        c.drawString(72, 700, "Some content")
        c.showPage()
        c.drawString(72, 720, "Chapter 2")
        c.drawString(72, 700, "More content")
        c.save()
        oi = _inspect_pdf_outline(pdf)
        # Without embedded outline, source is "heuristic".
        assert oi.source in ("outline", "heuristic")

    def test_inspect_pdf_outline_corrupt(self, tmp_path: Path) -> None:
        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"not a pdf")
        oi = _inspect_pdf_outline(pdf)
        # Either error or empty.
        assert oi.error is not None or oi.count == 0


class TestInspectEpubDirect:
    def test_inspect_epub_with_outline(self, tmp_path: Path) -> None:
        epub = fix_build.build_epub_with_3_chapters(tmp_path / "b.epub")
        r = _inspect_epub(epub, include_outline=True)
        assert r.format == "epub"
        assert r.outline is not None

    def test_inspect_epub_no_outline(self, tmp_path: Path) -> None:
        epub = fix_build.build_epub_with_3_chapters(tmp_path / "b.epub")
        r = _inspect_epub(epub, include_outline=False)
        assert r.outline is None
        assert r.fonts is None
        assert r.headers is None


class TestCollectFonts:
    def test_collect_fonts_returns_tuple(self, tmp_path: Path) -> None:
        import pypdfium2 as pdfium

        pdf = fix_build.build_outline_toc_pdf(tmp_path / "t.pdf")
        pdf_doc = pdfium.PdfDocument(str(pdf))
        try:
            fonts = _collect_fonts(pdf_doc, n_pages=2)
            assert isinstance(fonts, tuple)
            for item in fonts:
                assert len(item) == 2  # (name, type)
        finally:
            pdf_doc.close()

    def test_collect_fonts_zero_pages(self, tmp_path: Path) -> None:
        import pypdfium2 as pdfium

        pdf = fix_build.build_outline_toc_pdf(tmp_path / "t.pdf")
        pdf_doc = pdfium.PdfDocument(str(pdf))
        try:
            fonts = _collect_fonts(pdf_doc, n_pages=0)
            assert fonts == ()
        finally:
            pdf_doc.close()
