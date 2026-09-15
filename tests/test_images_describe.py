"""Tests de :mod:`capmd.llm` y de ``--describe-images`` en CLI (fase E6)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from capmd import cli as cli_module
from capmd.cli import app
from capmd.llm import (
    DEFAULT_MODELS,
    build_llm_client,
    detect_provider_from_env,
)

# ---------- helpers ----------


@pytest.fixture(autouse=True)
def _reset_warned_flag() -> None:
    """Cada test empieza con el flag global reseteado."""
    cli_module._reset_llm_warned_once()
    yield
    cli_module._reset_llm_warned_once()


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)


# ---------- detect_provider_from_env ----------


def test_detect_provider_openai_from_env(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert detect_provider_from_env() == "openai"


def test_detect_provider_anthropic_from_env(
    _clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    assert detect_provider_from_env() == "anthropic"


def test_detect_provider_google_from_env(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-key")
    assert detect_provider_from_env() == "google"


def test_detect_provider_priority_openai_first(
    _clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("GOOGLE_API_KEY", "goog")
    assert detect_provider_from_env() == "openai"


def test_detect_provider_returns_none_when_no_env(_clean_env: None) -> None:
    assert detect_provider_from_env() is None


# ---------- build_llm_client ----------


def test_build_llm_client_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="proveedor LLM desconocido"):
        build_llm_client("bogus")


def test_build_llm_client_mock_returns_none() -> None:
    assert build_llm_client("mock") is None


def test_build_llm_client_missing_openai_sdk_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si ``openai`` no está instalado y se pide provider=openai → ImportError con hint."""
    # Forzar que ``import openai`` falle.
    hidden = {"openai": None, "anthropic": None, "google": None, "google.genai": None}
    blocked_openai = ModuleNotFoundError("No module named 'openai'")

    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def fake_import(name, *args, **kwargs):
        if name in hidden and name == "openai":
            raise blocked_openai
        return real_import(name, *args, **kwargs)

    # Para ``from google import genai`` el nombre del módulo es "google".
    # Para simplificar, simulamos solo openai.
    with (
        patch.object(sys, "meta_path", []),
        patch("builtins.__import__", side_effect=fake_import),
        pytest.raises(ImportError, match="openai SDK requerido"),
    ):
        build_llm_client("openai")


def test_build_llm_client_unknown_provider_with_dash() -> None:
    with pytest.raises(ValueError):
        build_llm_client("un-real-provider")


# ---------- Engine ----------


def test_engine_with_llm_client_enables_plugins() -> None:
    from capmd.convert import Engine

    mock_client = MagicMock()
    engine = Engine(llm_client=mock_client)
    assert engine.llm_enabled is True


def test_engine_without_llm_plugins_disabled() -> None:
    from capmd.convert import Engine

    engine = Engine()
    assert engine.llm_enabled is False
    assert isinstance(engine, Engine)


def test_engine_with_explicit_enable_plugins_no_llm() -> None:
    from capmd.convert import Engine

    engine = Engine(enable_plugins=True)
    assert engine.llm_enabled is False


# ---------- _resolve_llm_client ----------


def test_resolve_llm_client_returns_none_when_disabled() -> None:
    client, model = cli_module._resolve_llm_client(
        describe_images=False,
        describe_provider="auto",
        describe_model=None,
    )
    assert client is None
    assert model is None


def test_resolve_llm_client_warns_once_when_no_key(
    _clean_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="capmd.cli"):
        client1, model1 = cli_module._resolve_llm_client(
            describe_images=True,
            describe_provider="auto",
            describe_model=None,
        )
        client2, model2 = cli_module._resolve_llm_client(
            describe_images=True,
            describe_provider="auto",
            describe_model=None,
        )

    # Ambas llamadas → (None, None) por la falta de key.
    assert client1 is None and model1 is None
    assert client2 is None and model2 is None

    # Solo UN warning (singleton warn-once).
    warnings = [
        r for r in caplog.records if "describe" in r.message.lower() or "API key" in r.message
    ]
    assert len(warnings) == 1


def test_resolve_llm_client_returns_mock_client_when_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el usuario monkeypatchea ``build_llm_client``, _resolve debe usar el mock."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    sentinel_client = MagicMock()

    def fake_factory(provider: str, model: str | None = None) -> object:
        return sentinel_client

    monkeypatch.setattr("capmd.config.build_llm_client", fake_factory)

    client, model = cli_module._resolve_llm_client(
        describe_images=True,
        describe_provider="auto",
        describe_model=None,
    )

    assert client is sentinel_client
    assert model == DEFAULT_MODELS["openai"]


def test_resolve_llm_client_anthropic_provider_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    sentinel_client = MagicMock()

    def fake_factory(provider: str, model: str | None = None) -> object:
        return sentinel_client

    monkeypatch.setattr("capmd.config.build_llm_client", fake_factory)

    client, model = cli_module._resolve_llm_client(
        describe_images=True,
        describe_provider="anthropic",
        describe_model="claude-3-haiku-20240307",
    )

    assert client is sentinel_client
    assert model == "claude-3-haiku-20240307"


def test_resolve_llm_client_invalid_provider_raises_badparam() -> None:
    import typer as _typer

    with pytest.raises(_typer.BadParameter):
        cli_module._resolve_llm_client(
            describe_images=True,
            describe_provider="bogus",
            describe_model=None,
        )


def test_resolve_llm_client_missing_api_key_warns_when_provider_explicit(
    _clean_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="capmd.cli"):
        client, model = cli_module._resolve_llm_client(
            describe_images=True,
            describe_provider="openai",
            describe_model=None,
        )

    assert client is None and model is None
    warnings = [r for r in caplog.records if "OPENAI_API_KEY" in r.message]
    assert len(warnings) == 1


# ---------- CLI integration ----------


def _run_convert(args: list[str]) -> object:
    runner = CliRunner()
    return runner.invoke(app, args)


@pytest.fixture
def midpage_pdf(tmp_path: Path) -> Path:
    from tests.fixtures.build import build_text_with_midpage_image_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "midpage.pdf"
    build_text_with_midpage_image_pdf(pdf, work)
    return pdf


def test_cli_describe_images_without_key_runs_anyway(
    midpage_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin API key + --describe-images → exit 0, warning único, output normal."""
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    out_md = tmp_path / "out.md"
    result = _run_convert(["convert", str(midpage_pdf), "-o", str(out_md), "--describe-images"])

    assert result.exit_code == 0, result.output
    assert "API key" in result.output or "API key" in (result.stderr or "")
    assert out_md.exists()


def test_cli_describe_images_anthropic_provider_flag(
    midpage_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--describe-provider=anthropic`` con key mockeada funciona sin abortar."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    sentinel_client = MagicMock()
    monkeypatch.setattr("capmd.config.build_llm_client", lambda p, m=None: sentinel_client)

    out_md = tmp_path / "out.md"
    result = _run_convert(
        [
            "convert",
            str(midpage_pdf),
            "-o",
            str(out_md),
            "--describe-images",
            "--describe-provider",
            "anthropic",
        ]
    )

    # No aborta (puede o no incluir descripciones — mockeado).
    assert result.exit_code == 0, result.output


def test_cli_describe_model_override(
    midpage_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--describe-model=custom`` → Engine recibe ese nombre de modelo."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured = {}

    def fake_factory(provider: str, model: str | None = None) -> object:
        captured["provider"] = provider
        captured["model"] = model
        return MagicMock()

    monkeypatch.setattr("capmd.config.build_llm_client", fake_factory)

    out_md = tmp_path / "out.md"
    result = _run_convert(
        [
            "convert",
            str(midpage_pdf),
            "-o",
            str(out_md),
            "--describe-images",
            "--describe-model",
            "gpt-4o",
        ]
    )

    assert result.exit_code == 0, result.output
    # El model default resuelto es gpt-4o (el que pasamos), no el default de OPENAI.
    assert captured.get("model") == "gpt-4o"


def test_cli_describe_images_help_text_shown() -> None:
    """Smoke: --describe-images aparece en la ayuda."""
    result = _run_convert(["convert", "--help"])
    assert result.exit_code == 0
    assert "--describe-images" in result.output
