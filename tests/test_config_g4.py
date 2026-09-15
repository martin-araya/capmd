"""Tests CLI para G4 — ``capmd config init`` / ``capmd config show``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd import config as _capmd_config
from capmd.cli import app
from capmd.config_init import render_default_toml

# Referencia al load_config ORIGINAL (antes de cualquier monkeypatch).
_original_load_config = _capmd_config.load_config


def _patch_loader(
    monkeypatch: pytest.MonkeyPatch,
    original_fn,
    *,
    project_toml: Path | None,
    env: dict[str, str] | None,
    forward_env: bool = False,
    global_toml_path: Path | None = None,
) -> None:
    """Monkeypatchea ``capmd.config.load_config`` con un wrapper que
    SIEMPRE llama al original (evita recursión) y reemplaza las rutas
    con las del fixture, ignorando las del caller.

    Si ``forward_env=True``, ``env=None`` del caller se reemplaza por
    ``os.environ`` (para tests que setean env vars antes de invocar).
    """

    def final_wrapper(*, env=None, project_toml=None, global_toml=None):
        effective_env = (os.environ if forward_env else {}) if env is None else env
        # IGNORAMOS project_toml y global_toml del caller; el fixture
        # del test manda (los defaults del módulo
        # ``capmd.config.PROJECT_TOML`` / ``GLOBAL_TOML`` se cachearon al
        # import y no respetan monkeypatch sobre ``tmp_path`` / ``HOME``).
        return original_fn(
            env=effective_env,
            project_toml=project_toml_arg,  # type: ignore[name-defined]
            global_toml=global_toml_arg,  # type: ignore[name-defined]
        )

    project_toml_arg = project_toml
    global_toml_arg = global_toml_path

    monkeypatch.setattr(_capmd_config, "load_config", final_wrapper)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _isolate_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """Hace que ``$HOME`` apunte a ``tmp_path`` y devuelve el path."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_writes_default_project_toml(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["config", "init"])
    assert r.exit_code == 0, r.output
    target = tmp_path / "capmd.toml"
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    assert "out_dir" in body
    assert "page_offset" in body
    assert "[cleaners]" in body
    assert "[books." in body


def test_init_global_writes_under_home(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = _isolate_home(monkeypatch, tmp_path)
    r = runner.invoke(app, ["config", "init", "--target", "global"])
    assert r.exit_code == 0, r.output
    target = fake_home / ".config" / "capmd" / "config.toml"
    assert target.exists()


def test_init_stdout_does_not_write_file(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["config", "init", "--stdout"])
    assert r.exit_code == 0, r.output
    assert "out_dir" in r.output
    assert not (tmp_path / "capmd.toml").exists()


def test_init_refuses_overwrite_without_force(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "capmd.toml"
    target.write_text("existing content", encoding="utf-8")
    r = runner.invoke(app, ["config", "init"])
    assert r.exit_code != 0
    assert target.read_text(encoding="utf-8") == "existing content"


def test_init_force_overwrites(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "capmd.toml"
    target.write_text("OLD", encoding="utf-8")
    r = runner.invoke(app, ["config", "init", "--force"])
    assert r.exit_code == 0, r.output
    body = target.read_text(encoding="utf-8")
    assert "OLD" not in body
    assert "[cleaners]" in body


def test_init_creates_parent_dirs(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = _isolate_home(monkeypatch, tmp_path)
    # pre-condition: ~/.config/capmd no existe.
    assert not (fake_home / ".config" / "capmd").exists()
    r = runner.invoke(app, ["config", "init", "--target", "global"])
    assert r.exit_code == 0, r.output
    assert (fake_home / ".config" / "capmd").is_dir()


def test_render_default_toml_contains_required_keys() -> None:
    body = render_default_toml(target="global")
    assert "# ~/.config/capmd/config.toml" in body
    assert "out_dir" in body
    assert "image_format" in body
    assert "page_offset" in body
    assert "[cleaners]" in body
    assert "[images]" in body
    assert "[books." in body


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_default_format_is_table(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "capmd.toml"
    toml.write_text("page_offset = 5\n", encoding="utf-8")
    _patch_loader(
        monkeypatch,
        _capmd_config.load_config.__wrapped__  # type: ignore[attr-defined]
        if hasattr(_capmd_config.load_config, "__wrapped__")
        else _original_load_config,
        project_toml=toml,
        env={},
    )

    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0, r.output
    assert "Effective configuration" in r.output
    assert "Top-level" in r.output
    assert "page_offset" in r.output
    assert "project" in r.output  # source label


def test_show_json_is_parseable(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=tmp_path / "no-project.toml",
        env={},
    )

    r = runner.invoke(app, ["config", "show", "--json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert "top_level" in payload
    assert "toml_sources" in payload
    assert "books" in payload
    assert "active_env_vars" in payload
    assert payload["top_level"]["page_offset"] == 0
    assert payload["top_level"]["image_format"] == "png"


def test_show_reflects_project_toml_override(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "capmd.toml"
    toml.write_text("page_offset = 3\n", encoding="utf-8")
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=toml,
        env={},
    )

    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0, r.output
    body = r.output
    # page_offset value y source ambos en la tabla.
    assert "3" in body
    assert "page_offset" in body
    assert "project" in body


def test_show_reflects_global_toml_override(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = _isolate_home(monkeypatch, tmp_path)
    global_toml = fake_home / ".config" / "capmd" / "config.toml"
    global_toml.parent.mkdir(parents=True, exist_ok=True)
    global_toml.write_text('image_format = "webp"\n', encoding="utf-8")
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=tmp_path / "no-project.toml",
        env={},
        global_toml_path=global_toml,
    )

    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0, r.output
    assert "webp" in r.output
    assert "global" in r.output


def test_show_reflects_env_var_override(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAPMD_IMAGE_FORMAT", "webp")
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=tmp_path / "no-project.toml",
        env=None,
        forward_env=True,
    )

    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0, r.output
    body = r.output
    assert "webp" in body
    assert "image_format" in body
    assert "env" in body


def test_show_lists_books_section(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "capmd.toml"
    toml.write_text(
        '[books."alpha"]\npage_offset = 2\n\n[books."beta"]\nimage_format = "webp"\n',
        encoding="utf-8",
    )
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=toml,
        env={},
    )

    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0, r.output
    assert "alpha" in r.output
    assert "beta" in r.output
    assert "page_offset=2" in r.output
    assert "image_format=webp" in r.output


def test_show_book_flag_pre_resolves_profile(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "capmd.toml"
    toml.write_text(
        '[books."x"]\npage_offset = 7\nimage_format = "webp"\n',
        encoding="utf-8",
    )
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=toml,
        env={},
    )

    r = runner.invoke(app, ["config", "show", "--book", "x"])
    assert r.exit_code == 0, r.output
    body = r.output
    assert "7" in body
    assert "webp" in body
    assert "book:x" in body


def test_show_unknown_book_errors(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=tmp_path / "no-project.toml",
        env={},
    )

    r = runner.invoke(app, ["config", "show", "--book", "ghost"])
    assert r.exit_code != 0
    assert "ghost" in r.output or "ghost" in (r.stderr or "")


def test_show_includes_active_env_vars(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAPMD_OUT_DIR", "/tmp/from-env")
    monkeypatch.delenv("CAPMD_PAGE_OFFSET", raising=False)
    monkeypatch.delenv("CAPMD_IMAGE_FORMAT", raising=False)
    _patch_loader(
        monkeypatch,
        _original_load_config,
        project_toml=tmp_path / "no-project.toml",
        env=None,
        forward_env=True,
    )

    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0, r.output
    assert "CAPMD_OUT_DIR" in r.output
    assert "/tmp/from-env" in r.output
    assert "applied" in r.output
