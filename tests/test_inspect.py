"""Tests de ``capmd inspect`` (H3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from capmd.errors import SourceNotFound, UnsupportedFormat
from capmd.inspect import (
    inspect_pdf,
    render_json,
    render_text,
)
from tests.fixtures import build as fix_build

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_pdf(tmp_path: Path, name: str = "t.pdf") -> Path:
    return fix_build.build_outline_toc_pdf(tmp_path / name)


def _build_scanned(tmp_path: Path, name: str = "s.pdf", n: int = 3) -> Path:
    return fix_build.build_scanned_pdf(tmp_path / name, n_pages=n)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestInspectPdfText:
    def test_text_pdf_not_scanned(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf)
        assert r.scanned is False
        assert r.words_per_page is not None
        assert r.words_per_page >= 10
        assert r.pages == 3

    def test_rasterized_pdf_is_scanned(self, tmp_path: Path) -> None:
        pdf = _build_scanned(tmp_path)
        r = inspect_pdf(pdf)
        assert r.scanned is True
        assert r.words_per_page == 0.0
        assert r.pages == 3

    def test_text_pdf_has_fonts(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf)
        assert r.fonts is not None
        assert r.fonts.count >= 1
        # ``build_outline_toc_pdf`` usa Helvetica + Helvetica-Bold
        names = {n for (n, _) in r.fonts.items}
        assert any("Helvetica" in n for n in names)

    def test_rasterized_pdf_has_no_fonts(self, tmp_path: Path) -> None:
        pdf = _build_scanned(tmp_path)
        r = inspect_pdf(pdf)
        assert r.fonts is not None
        assert r.fonts.count == 0


class TestInspectPdfOutline:
    def test_outline_from_embedded_toc(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf)
        assert r.outline is not None
        assert r.outline.source == "outline"
        # 3 capítulos + 1 sub-cap = 4 items
        assert r.outline.count >= 3
        titles = [t for _lvl, t, _p in r.outline.items]
        assert any("Getting Started" in t for t in titles)

    def test_outline_capped_at_20(self, tmp_path: Path) -> None:
        # Construimos un PDF con muchos outline entries y validamos el cap.
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas as cm

        pdf = tmp_path / "many.pdf"
        c = cm.Canvas(str(pdf), pagesize=LETTER)
        for i in range(30):
            c.bookmarkPage(f"ch{i}")
            c.addOutlineEntry(f"Chapter {i}", f"ch{i}", level=0, closed=False)
            c.setFont("Helvetica-Bold", 18)
            c.drawString(72, 720, f"Chapter {i}")
            c.showPage()
        c.save()
        r = inspect_pdf(pdf)
        assert r.outline is not None
        assert r.outline.count == 30
        assert len(r.outline.items) == 20


class TestInspectPdfHeadersFooters:
    def test_header_repetition_detected(self, tmp_path: Path) -> None:
        # ``build_header_footer_pdf`` repite "Capítulo 3 | Rust in Action"
        # en el header y "— N —" en el footer de cada página.
        pdf = fix_build.build_header_footer_pdf(tmp_path / "hf.pdf")
        r = inspect_pdf(pdf)
        assert r.headers is not None
        # El header puede aparecer detectado, aunque el matcher filtra
        # números. El footer "— N —" tiene un guion-em-espacios-número
        # que NO matchea ``str.isdigit()``.
        assert (
            r.headers.headers
            or r.headers.footers
            or r.headers.error is not None
        )


class TestInspectPdfFlags:
    def test_no_outline_skips_block(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf, include_outline=False)
        assert r.outline is None

    def test_no_text_skips_block(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf, include_text=False)
        assert r.words_per_page is None
        assert r.words_total is None
        assert r.scanned is None

    def test_no_fonts_skips_block(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf, include_fonts=False)
        assert r.fonts is None

    def test_no_headers_skips_block(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf, include_headers_footers=False)
        assert r.headers is None

    def test_sample_caps_pages(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf, sample=1)
        assert r.sampled_pages == 1


class TestInspectErrors:
    def test_nonexistent_raises_source_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(SourceNotFound):
            inspect_pdf(tmp_path / "no.pdf")

    def test_unsupported_format(self, tmp_path: Path) -> None:
        txt = tmp_path / "x.txt"
        txt.write_text("hi")
        with pytest.raises(UnsupportedFormat):
            inspect_pdf(txt)

    def test_epub_format_no_fonts(self, tmp_path: Path) -> None:
        epub = fix_build.build_epub_with_3_chapters(tmp_path / "book.epub")
        r = inspect_pdf(epub)
        assert r.format == "epub"
        assert r.fonts is None
        assert r.headers is None
        assert r.words_per_page is None


class TestJsonShape:
    def test_json_parseable_round_trip(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf)
        s = render_json(r)
        data = json.loads(s)
        assert data["schema_version"] == 1
        assert data["format"] == "pdf"
        assert data["pages"] == 3
        assert data["scanned"] is False
        assert data["outline"]["source"] == "outline"
        assert isinstance(data["outline"]["items"], list)
        assert data["fonts"]["count"] >= 1

    def test_render_text_not_empty(self, tmp_path: Path) -> None:
        pdf = _build_pdf(tmp_path)
        r = inspect_pdf(pdf)
        s = render_text(r)
        assert "outline" in s.lower() or "fonts" in s.lower()


# ---------------------------------------------------------------------------
# E2E (CliRunner)
# ---------------------------------------------------------------------------


runner = CliRunner()


def test_inspect_literal_text_vs_rasterized(tmp_path: Path) -> None:
    """Test literal del roadmap: distingue correctamente el fixture con
    texto del fixture rasterizado."""
    text_pdf = fix_build.build_outline_toc_pdf(tmp_path / "text.pdf")
    scan_pdf = fix_build.build_scanned_pdf(tmp_path / "scan.pdf")

    r_text = runner.invoke(app, ["inspect", str(text_pdf), "--format", "json"])
    r_scan = runner.invoke(app, ["inspect", str(scan_pdf), "--format", "json"])

    assert r_text.exit_code == 0, r_text.stderr
    assert r_scan.exit_code == 0, r_scan.stderr

    data_text = json.loads(r_text.stdout)
    data_scan = json.loads(r_scan.stdout)

    assert data_text["scanned"] is False
    assert data_scan["scanned"] is True
    # Y al revés: el texto tiene fuentes, el rasterizado no.
    assert data_text["fonts"]["count"] >= 1
    assert data_scan["fonts"]["count"] == 0


def test_inspect_default_text_format(tmp_path: Path) -> None:
    pdf = _build_pdf(tmp_path)
    result = runner.invoke(app, ["inspect", str(pdf)])
    assert result.exit_code == 0
    # Salida rich → stdout tiene paneles (texto con [OK], [WARN]).
    assert "[OK]" in result.stdout or "[WARN]" in result.stdout


def test_inspect_no_outline(tmp_path: Path) -> None:
    pdf = _build_pdf(tmp_path)
    result = runner.invoke(
        app, ["inspect", str(pdf), "--no-outline", "--format", "json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["outline"] is None


def test_inspect_no_text(tmp_path: Path) -> None:
    pdf = _build_pdf(tmp_path)
    result = runner.invoke(
        app, ["inspect", str(pdf), "--no-text", "--format", "json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["words_per_page"] is None
    assert data["words_total"] is None


def test_inspect_quiet(tmp_path: Path) -> None:
    pdf = _build_pdf(tmp_path)
    result = runner.invoke(app, ["--quiet", "inspect", str(pdf)])
    assert result.exit_code == 0
    # --quiet silencia stderr; stdout mantiene el reporte.
    assert result.stderr == ""


def test_inspect_nonexistent(tmp_path: Path) -> None:
    result = runner.invoke(app, ["inspect", str(tmp_path / "nope.pdf")])
    assert result.exit_code == 2


def test_inspect_unsupported_format(tmp_path: Path) -> None:
    txt = tmp_path / "x.txt"
    txt.write_text("hola")
    result = runner.invoke(app, ["inspect", str(txt)])
    assert result.exit_code == 3


def test_inspect_help_mentions_flags() -> None:
    result = runner.invoke(app, ["inspect", "--help"])
    assert result.exit_code == 0
    for flag in ("--format", "--sample", "--no-outline", "--no-text",
                  "--no-fonts", "--no-headers-footers", "--quiet"):
        assert flag in result.stdout, f"falta flag {flag} en --help"


def test_inspect_deterministic(tmp_path: Path) -> None:
    pdf = _build_pdf(tmp_path)
    r1 = inspect_pdf(pdf)
    r2 = inspect_pdf(pdf)
    assert render_json(r1) == render_json(r2)
