"""Smoke tests de la fase A1."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd import __version__
from capmd.cli import app


def test_version_string() -> None:
    assert __version__ == "0.1.0"


def test_help_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "capmd" in result.stdout.lower()


def test_no_args_shows_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 0


def test_package_layout_is_src() -> None:
    pkg_root = Path(__file__).resolve().parent.parent / "src" / "capmd"
    assert pkg_root.is_dir()
    assert (pkg_root / "__init__.py").is_file()
    assert (pkg_root / "cli.py").is_file()


def test_version_command_prints_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"capmd {__version__}"


def test_version_uses_importlib_metadata() -> None:
    assert metadata.version("capmd") == __version__


def test_verbose_flag_is_accepted_before_subcommand() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--verbose", "version"])
    assert result.exit_code == 0
    assert "capmd" in result.stdout


def test_verbose_double_is_accepted() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["-vv", "version"])
    assert result.exit_code == 0
    assert "capmd" in result.stdout


def test_resolve_version_falls_back_to_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    from capmd.cli import _resolve_version

    def _raise(_: str) -> str:
        raise metadata.PackageNotFoundError("capmd")

    monkeypatch.setattr(metadata, "version", _raise)
    assert _resolve_version() == __version__


def test_verbose_flag_appears_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--verbose" in result.stdout
    assert "-v" in result.stdout
