"""Tests del logging (A4)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd import __version__
from capmd.cli import app
from capmd.logging import configure_logging, get_logger


def setup_function(_: object) -> None:
    """Reset entre tests: capmd logger sin handlers, nivel WARNING."""
    configure_logging(0)


def test_default_level_is_warning() -> None:
    logger = get_logger()
    assert logger.level == logging.WARNING


def test_verbose_1_sets_info() -> None:
    configure_logging(1)
    assert get_logger().level == logging.INFO


def test_verbose_2_sets_debug() -> None:
    configure_logging(2)
    assert get_logger().level == logging.DEBUG


def test_verbose_caps_at_debug() -> None:
    configure_logging(99)
    assert get_logger().level == logging.DEBUG


def test_configure_logging_is_idempotent() -> None:
    configure_logging(2)
    configure_logging(2)
    configure_logging(2)
    assert len(get_logger().handlers) == 1


def test_log_emitted_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(2)
    get_logger().debug("hola debug")
    captured = capsys.readouterr()
    assert "hola debug" in captured.err
    assert "hola debug" not in captured.out


def test_log_suppressed_at_default_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(0)
    get_logger().info("no debería verse")
    get_logger().debug("tampoco")
    captured = capsys.readouterr()
    assert "no debería verse" not in captured.err
    assert "tampoco" not in captured.err


def test_info_visible_with_verbose_1(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(1)
    get_logger().info("info msg")
    captured = capsys.readouterr()
    assert "info msg" in captured.err


def test_propagate_is_false() -> None:
    configure_logging(2)
    assert get_logger().propagate is False


def test_get_logger_with_name() -> None:
    sub = get_logger("clean")
    assert sub.name == "capmd.clean"


def test_convert_with_vv_does_not_pollute_stdout(tmp_path: Path) -> None:
    """Test literal del roadmap: capmd convert x.pdf > out.md con -vv."""
    runner = CliRunner()
    real = tmp_path / "x.pdf"
    real.write_bytes(b"%PDF-1.4\n")

    result = runner.invoke(app, ["-vv", "convert", str(real)])
    assert "DEBUG" not in result.stdout
    assert "INFO" not in result.stdout
    assert "convirtiendo" in result.stderr


def test_convert_no_verbose_keeps_stdout_clean(tmp_path: Path) -> None:
    runner = CliRunner()
    real = tmp_path / "x.pdf"
    real.write_bytes(b"%PDF-1.4\n")

    result = runner.invoke(app, ["convert", str(real)])
    assert "INFO" not in result.stdout
    assert "DEBUG" not in result.stdout
    assert "convirtiendo" not in result.stderr


def test_version_command_still_works() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert f"capmd {__version__}" in result.stdout
