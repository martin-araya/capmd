"""Tests e2e del reporte de calidad (F6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# --- helpers --------------------------------------------------------------


def _stderr(result) -> str:
    """Devuelve stderr concatenado o ``result.output`` (typer CliRunner usa
    `result.output` como sink mixto)."""
    if result.stderr:
        return result.stderr
    return str(result.output or "")


def _scanned_pdf(tmp_path: Path) -> Path:
    return build.build_scanned_pdf(tmp_path / "scanned.pdf")


def _normal_pdf(tmp_path: Path) -> Path:
    return build.build_headings_pdf(tmp_path / "Rust Handbook.pdf")


# --- Literal test del roadmap F6 ------------------------------------------


def test_scanned_pdf_triggers_empty_output_warning(tmp_path: Path) -> None:
    """Test literal F6: PDF escaneado (sin texto) dispara warnings."""
    pdf = _scanned_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(app, ["convert", str(pdf), "--out", str(out_dir)])
    assert result.exit_code == 0, result.stderr

    capmd_json = out_dir / "scanned" / "full" / "capmd.json"
    assert capmd_json.exists()
    payload = json.loads(capmd_json.read_text(encoding="utf-8"))
    joined = "\n".join(payload["warnings"]).lower()
    # El PDF escaneado dispara empty_output y scanned_pdf en stderr; el
    # JSON persiste los mensajes legibles de los warnings.
    assert "output vacío" in joined or "0 palabras" in joined, (
        f"empty_output no aparece en warnings: {payload['warnings']}"
    )
    assert "escaneado" in joined, (
        f"warning de escaneado no aparece: {payload['warnings']}"
    )


def test_scanned_pdf_warning_visible_in_stderr(tmp_path: Path) -> None:
    pdf = _scanned_pdf(tmp_path)
    result = CliRunner().invoke(app, ["convert", str(pdf), "-o", str(tmp_path / "single.md")])
    assert result.exit_code == 0, result.stderr
    err = _stderr(result)
    assert "empty_output" in err or "escaneado" in err.lower()


# --- --strict --------------------------------------------------------------


def test_strict_with_warnings_exits_8(tmp_path: Path) -> None:
    pdf = _scanned_pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        ["convert", str(pdf), "-o", str(tmp_path / "single.md"), "--strict"],
    )
    assert result.exit_code == 8, f"esperaba 8, recibí {result.exit_code}"


def test_strict_without_warnings_exits_0(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        ["convert", str(pdf), "-o", str(tmp_path / "single.md"), "--strict"],
    )
    assert result.exit_code == 0, result.stderr


# --- --report-format -------------------------------------------------------


def test_default_report_is_json(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    result = CliRunner().invoke(app, ["convert", str(pdf), "-o", str(tmp_path / "single.md")])
    assert result.exit_code == 0
    err = _stderr(result)
    # El JSON es parseable y tiene schema_version.
    parsed = json.loads(err)
    assert "report_schema_version" in parsed
    assert parsed["format"] == "json"


def test_report_format_text_is_human_readable(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "convert", str(pdf),
            "-o", str(tmp_path / "single.md"),
            "--report-format", "text",
        ],
    )
    assert result.exit_code == 0
    err = _stderr(result)
    # Texto human-readable: no es JSON parseable.
    with pytest.raises(json.JSONDecodeError):
        json.loads(err)
    # Tiene stats clave en texto plano.
    assert "pages" in err
    assert "words" in err
    assert "pdf" in err


def test_report_format_explicit_json(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "convert", str(pdf),
            "-o", str(tmp_path / "single.md"),
            "--report-format", "json",
        ],
    )
    assert result.exit_code == 0
    err = _stderr(result)
    parsed = json.loads(err)
    assert "stats" in parsed
    assert "warnings" in parsed


# --- --no-warnings --------------------------------------------------------


def test_no_warnings_silences_warnings_in_text_output(tmp_path: Path) -> None:
    pdf = _scanned_pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "convert", str(pdf),
            "-o", str(tmp_path / "single.md"),
            "--report-format", "text",
            "--no-warnings",
        ],
    )
    assert result.exit_code == 0
    err = _stderr(result)
    # En texto, `--no-warnings` silencia "no_words:" / "scanned_pdf:" ...
    # La salida sigue teniendo stats, pero NO la sección de warnings.
    assert "warnings (" not in err or "código:" not in err.lower()


def test_no_warnings_still_persists_to_capmd_json(tmp_path: Path) -> None:
    """--no-warnings afecta solo stderr; capmd.json.warnings sigue completo."""
    pdf = _scanned_pdf(tmp_path)
    out_dir = tmp_path / "out_no_warnings"
    result = CliRunner().invoke(
        app,
        [
            "convert", str(pdf),
            "--out", str(out_dir),
            "--no-warnings",
        ],
    )
    assert result.exit_code == 0
    json_path = out_dir / "scanned" / "full" / "capmd.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    # Los warnings siguen persistidos en el JSON.
    assert payload["warnings"], "los warnings deben persistirse en capmd.json"


# --- normal PDF sin warnings ----------------------------------------------


def test_normal_pdf_triggers_no_warnings(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out_dir = tmp_path / "normal_out"
    result = CliRunner().invoke(app, ["convert", str(pdf), "--out", str(out_dir)])
    assert result.exit_code == 0
    json_path = next(iter(out_dir.rglob("capmd.json")))
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["warnings"] == [], (
        f"PDF normal no debería disparar warnings: {payload['warnings']}"
    )


# --- help / smoke ----------------------------------------------------------


def test_help_mentions_report_flags() -> None:
    result = CliRunner().invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--report-format" in result.stdout
    assert "--strict" in result.stdout
    assert "--no-warnings" in result.stdout


def test_report_emitted_to_stderr_not_stdout(tmp_path: Path) -> None:
    """El reporte va a stderr; stdout sigue siendo solo el markdown."""
    pdf = _normal_pdf(tmp_path)
    result = CliRunner().invoke(app, ["convert", str(pdf), "-o", str(tmp_path / "single.md")])
    assert result.exit_code == 0
    # stdout NO debe contener JSON del reporte.
    assert "report_schema_version" not in (result.stdout or ""), (
        f"reporte terminó en stdout: {result.stdout[:200]}"
    )
