"""Tests del modelo de errores y del handler global (A3)."""

from __future__ import annotations

from pathlib import Path

import typer
from typer.testing import CliRunner

from capmd.cli import app
from capmd.errors import (
    CapmdError,
    ConversionFailed,
    RangeOutOfBounds,
    SourceNotFound,
    UnsupportedFormat,
)


def test_capmd_error_default_exit_code() -> None:
    assert CapmdError("x").exit_code == 1


def test_subclass_exit_codes() -> None:
    assert SourceNotFound("x").exit_code == 2
    assert UnsupportedFormat("x").exit_code == 3
    assert RangeOutOfBounds("x").exit_code == 4
    assert ConversionFailed("x").exit_code == 5


def test_hint_is_optional() -> None:
    assert CapmdError("msg").hint is None
    assert CapmdError("msg", hint="h").hint == "h"


def test_str_returns_message() -> None:
    assert str(CapmdError("hello world")) == "hello world"


def test_convert_nonexistent_file_exits_2(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = tmp_path / "no-existe.pdf"
    result = runner.invoke(app, ["convert", str(missing)])
    assert result.exit_code == 2
    assert "no se encontró" in result.stderr
    assert "Sugerencia" in result.stderr


def test_convert_nonexistent_file_no_traceback(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = tmp_path / "no-existe.pdf"
    result = runner.invoke(app, ["convert", str(missing)])
    combined = result.stdout + result.stderr
    assert "Traceback" not in combined
    assert 'File "' not in combined


def test_convert_directory_raises_source_not_found(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(tmp_path)])
    assert result.exit_code == 2
    assert "no se encontró" in result.stderr


def test_convert_existing_file_succeeds_or_fails_gracefully(tmp_path: Path) -> None:
    """Tras B3, un PDF "casi válido" pasa por markitdown sin NotImplementedError.

    markitdown acepta blobs mínimos con header PDF y devuelve markdown
    (probablemente vacío). Lo importante es que ya no se lanza
    NotImplementedError (exit code != 0 con traceback).
    """
    runner = CliRunner()
    real = tmp_path / "x.pdf"
    real.write_bytes(b"%PDF-1.4\n")
    result = runner.invoke(app, ["convert", str(real)])
    combined = result.stdout + result.stderr
    assert "NotImplementedError" not in combined
    assert "Traceback" not in combined


def test_app_is_typer_instance() -> None:
    assert isinstance(app, typer.Typer)


def test_help_mentions_convert_command() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "convert" in result.stdout.lower()


def test_help_mentions_version_command() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.stdout.lower()


def test_error_rendered_to_stderr_not_stdout(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = tmp_path / "no-existe.pdf"
    result = runner.invoke(app, ["convert", str(missing)])
    assert "no se encontró" not in result.stdout
    assert "no se encontró" in result.stderr
