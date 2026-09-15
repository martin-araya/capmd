"""Tests e2e del dry-run (F7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build


def _normal_pdf(tmp_path: Path) -> Path:
    return build.build_headings_pdf(tmp_path / "Rust Handbook.pdf")


# --- Literal test del roadmap F7 ------------------------------------------


def test_dry_run_filesystem_unchanged(tmp_path: Path) -> None:
    """Test literal F7: --dry-run deja el filesystem del destino intacto."""
    pdf = _normal_pdf(tmp_path)
    out_dir = tmp_path / "DESTINATION"
    assert not out_dir.exists()

    result = CliRunner().invoke(
        app,
        ["convert", str(pdf), "--out", str(out_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.stderr

    # El dir destino NO debe existir después del dry-run.
    assert not out_dir.exists(), (
        f"--dry-run creó el destino: {out_dir}"
    )
    # El PDF source NO debe modificarse (el dry-run no toca el input).
    assert pdf.exists()


def test_dry_run_outputs_parseable_json_to_stdout(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        ["convert", str(pdf), "--out", str(out_dir), "--dry-run"],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["dry_run"] is True
    assert parsed["schema_version"] == 1
    assert parsed["output"]["kind"] == "tree"


# --- Different output kinds -----------------------------------------------


def test_dry_run_single_file_kind(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out_file = tmp_path / "single.md"
    result = CliRunner().invoke(
        app,
        ["convert", str(pdf), "-o", str(out_file), "--dry-run"],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["output"]["kind"] == "single-file"
    assert parsed["output"]["tree_files"] == [str(out_file)]
    # El archivo NO debe existir.
    assert not out_file.exists()


def test_dry_run_flat_kind(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out_dir = tmp_path / "flat"
    result = CliRunner().invoke(
        app,
        [
            "convert", str(pdf),
            "--out", str(out_dir),
            "--flat",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["output"]["kind"] == "flat"
    assert len(parsed["output"]["tree_files"]) == 1


# --- Format flags --------------------------------------------------------


def test_dry_run_format_text_is_human_readable(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        [
            "convert", str(pdf),
            "--out", str(out_dir),
            "--dry-run", "--dry-run-format", "text",
        ],
    )
    assert result.exit_code == 0
    # Texto no es JSON parseable.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    # Pero contiene marcadores humanos.
    assert "capmd dry-run" in result.stdout
    assert "input" in result.stdout


# --- --split -------------------------------------------------------------


def test_dry_run_with_split_h2_lists_sections(tmp_path: Path) -> None:
    pdf = build.build_four_h2_pdf(tmp_path / "Rust Handbook.pdf")
    out_dir = tmp_path / "split_out"
    result = CliRunner().invoke(
        app,
        [
            "convert", str(pdf),
            "--out", str(out_dir),
            "--split", "h2",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    files = parsed["output"]["tree_files"]
    # El plan incluye los archivos de sections/.
    assert any("sections/01-" in f for f in files), files
    assert any("sections/04-" in f for f in files), files
    assert any(f.endswith("sections/index.md") for f in files), files
    # Y no se escribió nada en out_dir.
    assert not out_dir.exists()


# --- --dry-run does NOT print markdown -----------------------------------


def test_dry_run_does_not_dump_markdown_to_stdout(tmp_path: Path) -> None:
    """El dry-run emite el plan, no el markdown."""
    pdf = _normal_pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        ["convert", str(pdf), "-o", str(tmp_path / "single.md"), "--dry-run"],
    )
    assert result.exit_code == 0
    # El stdout es JSON del plan, NO markdown con heading.
    parsed = json.loads(result.stdout)
    assert "report" in parsed
    # Aseguramos que el primer caracter no es '#' (inicio de markdown).
    assert not result.stdout.startswith("#")


# --- F6 report embebido -------------------------------------------------


def test_dry_run_includes_f6_report(tmp_path: Path) -> None:
    """El report de F6 está embebido dentro del plan."""
    pdf = _normal_pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        ["convert", str(pdf), "-o", str(tmp_path / "single.md"), "--dry-run"],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "report" in parsed
    assert "stats" in parsed["report"]
    assert "warnings" in parsed["report"]
    assert parsed["report"]["stats"]["source_format"] == "pdf"


def test_help_mentions_dry_run_flags() -> None:
    result = CliRunner().invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.stdout
    assert "--dry-run-format" in result.stdout
