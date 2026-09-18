"""Tests unitarios de ``capmd.compare`` (K5).

Cubre:
- Métricas (count_words, count_headings).
- Parser de page range.
- Detección de motores OCR disponibles.
- Detección de Azure routing disponible.
- Orchestrator run_compare con motores built-in / docintel / CU.
- Renderers (table, json).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from capmd.compare import (
    CompareReport,
    MotorResult,
    count_headings,
    count_words,
    detect_ocr_engines,
    parse_pages_string,
    render_report,
    run_compare,
)
from capmd.compare.motors import (
    _is_cu_available,
    _is_docintel_available,
)


# ---------------------------------------------------------------------------
# parse_pages_string
# ---------------------------------------------------------------------------


def test_parse_pages_string_single_range() -> None:
    """``"45-50"`` → ``[45, 46, ..., 50]``."""
    assert parse_pages_string("45-50") == list(range(45, 51))


def test_parse_pages_string_multiple_ranges() -> None:
    """``"1-3,7,10-12"`` mezcla rangos + singles."""
    assert parse_pages_string("1-3,7,10-12") == [1, 2, 3, 7, 10, 11, 12]


def test_parse_pages_string_empty_returns_none() -> None:
    """``None`` o vacío → ``None`` (todo el PDF)."""
    assert parse_pages_string(None) is None
    assert parse_pages_string("") is None
    assert parse_pages_string("   ") is None


def test_parse_pages_string_invalid_raises_value_error() -> None:
    """Formato inválido → ``ValueError``."""
    for bad in ("abc", "1-2-3", "1,,2", "1.5"):
        with pytest.raises(ValueError) as exc_info:
            parse_pages_string(bad)
        assert "page range" in str(exc_info.value).lower() or "inv" in str(exc_info.value).lower()


def test_parse_pages_string_inverted_range_raises_value_error() -> None:
    """``"5-3"`` (start > end) → ``ValueError``."""
    with pytest.raises(ValueError):
        parse_pages_string("5-3")


def test_parse_pages_string_zero_or_negative_raises_value_error() -> None:
    """``"0-5"`` o ``"-3"`` → ``ValueError`` (pages son 1-based)."""
    with pytest.raises(ValueError):
        parse_pages_string("0-5")


# ---------------------------------------------------------------------------
# count_words / count_headings
# ---------------------------------------------------------------------------


def test_count_words_empty() -> None:
    """``""`` → 0 palabras."""
    assert count_words("") == 0


def test_count_words_simple() -> None:
    """``"hello world foo bar"`` → 4."""
    assert count_words("hello world foo bar") == 4


def test_count_words_multiline() -> None:
    """``"line 1\nline 2\nline 3"`` → 6."""
    assert (
        count_words("line 1\nline 2\nline 3") == 6
    )  # split incluye el último token vacío si es \n


def test_count_words_extra_whitespace() -> None:
    """Multiples espacios / tabs cuentan como separadores."""
    assert count_words("a  b\tc\nd") == 4


def test_count_headings_detects_h1_to_h6() -> None:
    """Todos los niveles ``#`` a ``######`` cuentan."""
    md = "# Title\n## Sub\n### Sub\n#### Sub\n##### Sub\n###### Sub\nbody"
    assert count_headings(md) == 6


def test_count_headings_ignores_inline_hashes() -> None:
    """``text with #hash inline`` no cuenta (no arranca línea)."""
    assert count_headings("text with #hash inline") == 0
    # ``paragraph #1`` no es heading (el # está en medio del texto).
    # ``# but this counts`` es heading (arranca línea + espacio).
    assert count_headings("paragraph #1\n# but this counts") == 1


def test_count_headings_empty() -> None:
    """``""`` → 0."""
    assert count_headings("") == 0


# ---------------------------------------------------------------------------
# detect_ocr_engines / routing detection
# ---------------------------------------------------------------------------


def test_detect_ocr_engines_returns_empty_when_neither_installed() -> None:
    """Si ni ``tesseract`` ni ``ocrmypdf`` están en PATH → tupla vacía."""
    fake_which = lambda _: None
    with patch("capmd.compare.motors.shutil.which", fake_which):
        assert detect_ocr_engines() == ()


def test_detect_ocr_engines_returns_tesseract_when_installed() -> None:
    """``shutil.which("tesseract")`` retorna path → ``ocr-tesseract`` en tupla."""
    fake_which = lambda cmd: "/usr/bin/tesseract" if cmd == "tesseract" else None
    with patch("capmd.compare.motors.shutil.which", fake_which):
        assert detect_ocr_engines() == ("ocr-tesseract",)


def test_detect_ocr_engines_returns_both_when_installed() -> None:
    """Ambos binarios presentes → tupla con los 2."""
    fake_paths = {
        "tesseract": "/usr/bin/tesseract",
        "ocrmypdf": "/usr/bin/ocrmypdf",
    }
    fake_which = lambda cmd: fake_paths.get(cmd)
    with patch("capmd.compare.motors.shutil.which", fake_which):
        assert detect_ocr_engines() == ("ocr-tesseract", "ocr-ocrmypdf")


def test_is_cu_available_returns_true_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MARKITDOWN_CU_ENDPOINT`` set → True."""
    monkeypatch.setenv("MARKITDOWN_CU_ENDPOINT", "https://x")
    assert _is_cu_available() is True


def test_is_cu_available_returns_false_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin ``MARKITDOWN_CU_ENDPOINT`` → False."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)
    assert _is_cu_available() is False


def test_is_docintel_available_returns_true_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MARKITDOWN_DOCINTEL_ENDPOINT`` set → True."""
    monkeypatch.setenv("MARKITDOWN_DOCINTEL_ENDPOINT", "https://x")
    assert _is_docintel_available() is True


# ---------------------------------------------------------------------------
# run_compare — orchestrator
# ---------------------------------------------------------------------------


def _outline_pdf_with_pages(tmp_path: Path, n_pages: int = 20) -> Path:
    """Helper: crea un PDF con N páginas (usa fixture)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tests.fixtures import build

    return build.build_many_pages_pdf(tmp_path / "book.pdf", n_pages=n_pages)


def test_run_compare_only_builtin_when_no_env_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin env vars Azure → solo built-in corre; cu/docintel "skipped"."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)
    monkeypatch.delenv("MARKITDOWN_DOCINTEL_ENDPOINT", raising=False)
    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    report = run_compare(source=pdf, pages=None, timeout=60)

    motor_names = [m.name for m in report.motors]
    assert "built-in" in motor_names
    assert "content-understanding" not in motor_names
    assert "docintel" not in motor_names

    built_in = next(m for m in report.motors if m.name == "built-in")
    assert built_in.status == "ok"
    assert built_in.words > 0
    assert built_in.time_seconds > 0


def test_run_compare_with_cu_runs_built_in_and_cu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MARKITDOWN_CU_ENDPOINT`` set → 2 motores corren (built-in + cu)."""
    monkeypatch.setenv("MARKITDOWN_CU_ENDPOINT", "https://mock-cu.example")
    monkeypatch.delenv("MARKITDOWN_DOCINTEL_ENDPOINT", raising=False)

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    report = run_compare(source=pdf, pages=None, timeout=60)

    motor_names = [m.name for m in report.motors]
    assert "built-in" in motor_names
    assert "content-understanding" in motor_names
    assert "docintel" not in motor_names


def test_run_compare_with_docintel_runs_docintel_not_cu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MARKITDOWN_DOCINTEL_ENDPOINT`` set → docintel corre; cu no."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)
    monkeypatch.setenv("MARKITDOWN_DOCINTEL_ENDPOINT", "https://di.example")

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    report = run_compare(source=pdf, pages=None, timeout=60)

    motor_names = [m.name for m in report.motors]
    assert "docintel" in motor_names
    assert "content-understanding" not in motor_names


def test_run_compare_with_both_endpoints_runs_three_motors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambas env vars → 3 motores corren (built-in + docintel + cu)."""
    monkeypatch.setenv("MARKITDOWN_CU_ENDPOINT", "https://cu.example")
    monkeypatch.setenv("MARKITDOWN_DOCINTEL_ENDPOINT", "https://di.example")

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    report = run_compare(source=pdf, pages=None, timeout=60)

    motor_names = [m.name for m in report.motors]
    assert "built-in" in motor_names
    assert "docintel" in motor_names
    assert "content-understanding" in motor_names


def test_run_compare_motor_failure_does_not_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si CU/DocIntel falla (sin shim), built-in igual completa."""
    monkeypatch.setenv("MARKITDOWN_CU_ENDPOINT", "https://mock-cu.example")
    monkeypatch.delenv("MARKITDOWN_DOCINTEL_ENDPOINT", raising=False)
    # Sin CAPMD_MARKITDOWN_BIN: markitdown real no tiene extras Azure;
    # el motor marca error pero built-in sigue.
    monkeypatch.delenv("CAPMD_MARKITDOWN_BIN", raising=False)

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    report = run_compare(source=pdf, pages=None, timeout=10)

    built_in = next(m for m in report.motors if m.name == "built-in")
    assert built_in.status == "ok"
    cu = next(m for m in report.motors if m.name == "content-understanding")
    assert cu.status in ("ok", "error")  # depende del entorno real


def test_run_compare_pages_slicing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--pages "3-5"`` solo procesa pages 3-5."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)
    monkeypatch.delenv("MARKITDOWN_DOCINTEL_ENDPOINT", raising=False)

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=10)
    report = run_compare(source=pdf, pages="3-5", timeout=30)

    assert report.pages == "3-5"
    built_in = next(m for m in report.motors if m.name == "built-in")
    assert built_in.status == "ok"


def test_run_compare_invalid_pages_raises_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--pages "abc"`` → ``ValueError`` (origen del ``BadParameter`` en CLI)."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    with pytest.raises(ValueError):
        run_compare(source=pdf, pages="abc", timeout=30)


def test_run_compare_invalid_page_range_exceeds_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--pages "200-300"`` (PDF tiene 5) → ``ValueError``."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    with pytest.raises(ValueError) as exc_info:
        run_compare(source=pdf, pages="200-300", timeout=30)
    assert "excede" in str(exc_info.value) or "pages" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


def test_render_report_table_format_includes_motor_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renderer ``table`` incluye los nombres de los motores en el output."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)
    monkeypatch.delenv("MARKITDOWN_DOCINTEL_ENDPOINT", raising=False)

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    report = run_compare(source=pdf, pages=None, timeout=30)
    rendered = render_report(report, format="table")
    assert "built-in" in rendered
    assert "Comparador de motores" in rendered


def test_render_report_json_format_is_parseable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renderer ``json`` devuelve JSON parseable con la estructura esperada."""
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)
    monkeypatch.delenv("MARKITDOWN_DOCINTEL_ENDPOINT", raising=False)

    pdf = _outline_pdf_with_pages(tmp_path, n_pages=5)
    report = run_compare(source=pdf, pages=None, timeout=30)
    rendered = render_report(report, format="json")
    payload = json.loads(rendered)
    assert payload["source"].endswith("book.pdf")
    assert payload["pages"] is None
    assert isinstance(payload["motors"], list)
    assert len(payload["motors"]) >= 1
    for motor in payload["motors"]:
        assert "name" in motor
        assert "words" in motor
        assert "headings" in motor
        assert "time_seconds" in motor
        assert "status" in motor
        assert motor["status"] in ("ok", "skipped", "error")


def test_render_report_invalid_format_raises_value_error() -> None:
    """``format="xml"`` → ``ValueError``."""
    report = CompareReport(
        source=Path("/tmp/dummy.pdf"),
        pages=None,
        elapsed_seconds=0.5,
        motors=(),
    )
    with pytest.raises(ValueError) as exc_info:
        render_report(report, format="xml")
    assert "format" in str(exc_info.value).lower()
