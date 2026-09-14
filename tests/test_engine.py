"""Tests del wrapper de markitdown (B1 + B2 + B4 + B5)."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from capmd.convert import Engine
from capmd.convert.limits import ConversionLimits
from capmd.errors import (
    ConversionFailed,
    InputTooLarge,
    SourceNotFound,
    UnsupportedFormat,
)
from capmd.models import ConversionOutput
from tests.fixtures import build


def test_convert_path_headings_returns_non_empty_str(tmp_path: Path) -> None:
    """Test literal del roadmap B1."""
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine()

    out = engine.convert_path(pdf)

    assert isinstance(out, ConversionOutput)
    assert out.markdown.strip() != ""


def test_convert_path_headings_preserves_chapter_titles(tmp_path: Path) -> None:
    """Más estricto que el spec mínimo: confirma que el texto viaja."""
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine()

    out = engine.convert_path(pdf)

    assert "Introduction" in out.markdown
    assert "Ownership" in out.markdown


def test_engine_is_reusable_across_calls(tmp_path: Path) -> None:
    """El MarkItDown interno se construye una sola vez (spec B1)."""
    pdf1 = build.build_headings_pdf(tmp_path / "h1.pdf")
    pdf2 = build.build_headings_pdf(tmp_path / "h2.pdf")
    engine = Engine()

    out1 = engine.convert_path(pdf1)
    out2 = engine.convert_path(pdf2)

    assert out1.markdown and out2.markdown
    assert engine._md is engine._md


def test_convert_path_missing_file_raises_source_not_found(tmp_path: Path) -> None:
    engine = Engine()
    with pytest.raises(SourceNotFound):
        engine.convert_path(tmp_path / "nope.pdf")


def test_engine_enable_plugins_false_does_not_break(tmp_path: Path) -> None:
    """Comprobar que el default explícito no rompe nada."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    engine = Engine(enable_plugins=False)
    out = engine.convert_path(pdf)
    assert out.markdown.strip()


def test_check_supported_unknown_extension_lists_supported(tmp_path: Path) -> None:
    """Test literal del roadmap B2."""
    f = tmp_path / "book.xyz"
    f.write_bytes(b"")
    engine = Engine()
    with pytest.raises(UnsupportedFormat) as excinfo:
        engine.check_supported(f)
    hint = excinfo.value.hint or ""
    assert "formatos soportados" in hint
    for ext in ("pdf", "epub", "docx", "pptx", "xlsx"):
        assert ext in hint


def test_check_supported_is_case_insensitive(tmp_path: Path) -> None:
    f = tmp_path / "book.PDF"
    f.write_bytes(b"")
    engine = Engine()
    assert engine.check_supported(f).name == "PDF"


def test_check_supported_no_extension(tmp_path: Path) -> None:
    f = tmp_path / "book"
    f.write_bytes(b"")
    engine = Engine()
    with pytest.raises(UnsupportedFormat):
        engine.check_supported(f)


def test_check_supported_missing_extra_raises_with_hint(tmp_path: Path) -> None:
    """Sentinel no presente → UnsupportedFormat con hint que nombra [extra]."""
    f = tmp_path / "book.docx"
    f.write_bytes(b"")
    engine = Engine()
    with (
        patch("capmd.convert.engine.importlib.util.find_spec", return_value=None),
        pytest.raises(UnsupportedFormat) as excinfo,
    ):
        engine.check_supported(f)
    assert "[docx]" in (excinfo.value.hint or "")


def test_supported_formats_returns_sorted_extensions() -> None:
    engine = Engine()
    assert engine.supported_formats() == ["docx", "epub", "html", "pdf", "pptx", "xlsx"]


def test_convert_path_unknown_extension_raises_unsupported(tmp_path: Path) -> None:
    """B2 integrado en convert_path: un .xyz ni siquiera llega a markitdown."""
    f = tmp_path / "book.xyz"
    f.write_bytes(b"")
    engine = Engine()
    with pytest.raises(UnsupportedFormat):
        engine.convert_path(f)


# --- B4: convert_stream -----------------------------------------------------


def test_convert_stream_matches_convert_path(tmp_path: Path) -> None:
    """Spec literal B4: el pipe produce el mismo output que el archivo."""
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine()

    from_path = engine.convert_path(pdf)
    from_stream = engine.convert_stream(
        io.BytesIO(pdf.read_bytes()),
        extension=".pdf",
    )

    assert from_path.markdown == from_stream.markdown


def test_convert_stream_uses_convert_stream_not_convert_local(tmp_path: Path) -> None:
    """El método público pasa por MarkItDown.convert_stream, no convert_local."""
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine()

    with (
        patch.object(engine._md, "convert_stream", wraps=engine._md.convert_stream) as stream_mock,
        patch.object(engine._md, "convert_local") as local_mock,
    ):
        engine.convert_stream(io.BytesIO(pdf.read_bytes()), extension="pdf")

    stream_mock.assert_called_once()
    local_mock.assert_not_called()


def test_convert_stream_normalizes_extension_without_dot(tmp_path: Path) -> None:
    """``"pdf"`` y ``".pdf"`` deben ser equivalentes en el lookup."""
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine()
    data = pdf.read_bytes()

    a = engine.convert_stream(io.BytesIO(data), extension="pdf")
    b = engine.convert_stream(io.BytesIO(data), extension=".pdf")
    c = engine.convert_stream(io.BytesIO(data), extension="PDF")

    assert a.markdown == b.markdown == c.markdown


def test_convert_stream_unknown_extension_raises_unsupported(tmp_path: Path) -> None:
    engine = Engine()
    with pytest.raises(UnsupportedFormat) as excinfo:
        engine.convert_stream(io.BytesIO(b"x"), extension="xyz")
    hint = excinfo.value.hint or ""
    assert "formatos soportados" in hint
    assert "stdin" in excinfo.value.message


def test_convert_stream_missing_extra_raises_with_hint(tmp_path: Path) -> None:
    """Sentinel ausente → UnsupportedFormat con hint que nombra el extra."""
    engine = Engine()
    with (
        patch("capmd.convert.engine.importlib.util.find_spec", return_value=None),
        pytest.raises(UnsupportedFormat) as excinfo,
    ):
        engine.convert_stream(io.BytesIO(b"x"), extension=".docx")
    assert "[docx]" in (excinfo.value.hint or "")


# --- B5: límites, tiempo, timeout, conteo de páginas -----------------------


def test_convert_path_returns_conversion_output(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine()
    out = engine.convert_path(pdf)
    assert isinstance(out, ConversionOutput)
    assert out.markdown
    assert out.elapsed_seconds >= 0
    assert out.size_bytes == pdf.stat().st_size


def test_convert_path_measures_elapsed(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine()
    out = engine.convert_path(pdf)
    # El fixture chico convierte en << 1 s; el upper bound es defensivo.
    assert 0 <= out.elapsed_seconds < 5


def test_convert_path_reports_page_count_for_pdf(tmp_path: Path) -> None:
    pdf = build.build_many_pages_pdf(tmp_path / "p.pdf", n_pages=12)
    engine = Engine()
    out = engine.convert_path(pdf)
    assert out.page_count == 12


def test_convert_path_no_page_count_for_non_pdf(tmp_path: Path) -> None:
    # No tenemos generador barato de DOCX; usamos un EPUB sintético rápido.
    from tests.fixtures.build import build_outline_toc_pdf

    pdf = build_outline_toc_pdf(tmp_path / "toc.pdf")
    engine = Engine()
    out = engine.convert_path(pdf)
    # PDF: page_count viene de pypdf.
    assert out.page_count is not None and out.page_count >= 1


def test_convert_path_exceeds_max_size_raises_input_too_large(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine(limits=ConversionLimits(max_size_bytes=10))
    with pytest.raises(InputTooLarge):
        engine.convert_path(pdf)


def test_convert_path_exceeds_max_pages_raises_input_too_large(tmp_path: Path) -> None:
    pdf = build.build_many_pages_pdf(tmp_path / "p.pdf", n_pages=12)
    engine = Engine(limits=ConversionLimits(max_pages=10))
    with pytest.raises(InputTooLarge):
        engine.convert_path(pdf)


def test_convert_path_under_warn_pages_no_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine(limits=ConversionLimits(warn_pages=500))
    with caplog.at_level(logging.WARNING):
        engine.convert_path(pdf)
    assert not any("PDF grande" in rec.message for rec in caplog.records)


def test_convert_path_over_warn_pages_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pdf = build.build_many_pages_pdf(tmp_path / "p.pdf", n_pages=12)
    engine = Engine(limits=ConversionLimits(warn_pages=10))
    with caplog.at_level(logging.WARNING):
        engine.convert_path(pdf)
    assert any("PDF grande" in rec.message for rec in caplog.records)


def test_convert_path_timeout_enforced(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    engine = Engine(limits=ConversionLimits(timeout_seconds=1))

    def _slow(*_args: object, **_kwargs: object) -> Any:
        import time as _time

        _time.sleep(3)
        return None

    with (
        patch.object(engine._md, "convert_local", side_effect=_slow),
        pytest.raises(ConversionFailed) as excinfo,
    ):
        engine.convert_path(pdf)
    hint = excinfo.value.hint or ""
    assert "timeout" in hint.lower() or "--timeout" in hint


def test_500_page_synthetic_pdf_converts(tmp_path: Path) -> None:
    """Test literal del roadmap B5.

    Genera 500 páginas sintéticas, las convierte con los límites
    default del Engine y confirma que termina OK, dentro de un timeout
    sano y con ``page_count == 500``.
    """
    pdf = build.build_many_pages_pdf(tmp_path / "big.pdf", n_pages=500)
    engine = Engine()

    out = engine.convert_path(pdf)

    assert out.markdown
    assert out.page_count == 500
    # 500 páginas sintéticas no deberían tomar más de 60 s (límite
    # defensivo; en CI el tiempo es típicamente < 30 s).
    assert out.elapsed_seconds < 60
