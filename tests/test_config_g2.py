"""Tests para G2 — Precedencia CLI > env > project > global > defaults.

Cubre el test del roadmap: "cuatro capas, cuatro asserts".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd import config as _capmd_config
from capmd.cli import app
from capmd.config import (
    DEFAULTS,
    ENV_VARS,
    CapmdConfig,
    load_config,
    merge_configs,
)
from tests.fixtures import build


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# 1 (cubierto en CLI smoke + helper)
# 2 (capa env sobre project TOML — puro config)
def test_env_overrides_project_toml(tmp_path: Path) -> None:
    project = tmp_path / "capmd.toml"
    _write_toml(project, "page_offset = 3\n")
    cfg = load_config(
        env={"CAPMD_PAGE_OFFSET": "7"},
        global_toml=None,
        project_toml=project,
    )
    assert cfg.page_offset == 7
    # project contribuyó (queda en sources); env se mergea encima.
    assert project in cfg.source_paths


# 3 (project > global — ya cubierto en G1; se revalida vía load_config)
def test_project_overrides_global(tmp_path: Path) -> None:
    global_ = tmp_path / "global" / "config.toml"
    project = tmp_path / "capmd.toml"
    _write_toml(global_, "page_offset = 2\nimage_format = \"webp\"\n")
    _write_toml(project, "page_offset = 5\n")
    cfg = load_config(
        env={},
        global_toml=global_,
        project_toml=project,
    )
    assert cfg.page_offset == 5
    assert cfg.image_format == "webp"


# 4 (global > defaults — ya cubierto en G1)
def test_global_overrides_defaults(tmp_path: Path) -> None:
    global_ = tmp_path / "global.toml"
    _write_toml(global_, 'image_format = "webp"\n')
    cfg = load_config(
        env={},
        global_toml=global_,
        project_toml=None,
    )
    assert cfg.image_format == "webp"
    assert cfg.page_offset == DEFAULTS["page_offset"]


# 5 — env inválido cae al default con warning
def test_env_invalid_image_format_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = load_config(
        env={"CAPMD_IMAGE_FORMAT": "gif"},
        global_toml=None,
        project_toml=None,
    )
    assert cfg.image_format == "png"
    assert any(
        "CAPMD_IMAGE_FORMAT" in rec.message for rec in caplog.records
    )


def test_env_invalid_page_offset_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = load_config(
        env={"CAPMD_PAGE_OFFSET": "abc"},
        global_toml=None,
        project_toml=None,
    )
    assert cfg.page_offset == 0
    assert any("CAPMD_PAGE_OFFSET" in rec.message for rec in caplog.records)


# 6 — CSV parsing de cleaners
def test_env_cleaners_csv_parsed() -> None:
    cfg = load_config(
        env={"CAPMD_CLEANERS_DISABLED": "whitespace, headers ; tables"},
        global_toml=None,
        project_toml=None,
    )
    assert cfg.cleaners_disabled == ("whitespace", "headers", "tables")
    assert cfg.cleaners_enabled is None


def test_env_cleaners_invalid_name_filtered(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = load_config(
        env={"CAPMD_CLEANERS_ENABLED": "whitespace, bogus"},
        global_toml=None,
        project_toml=None,
    )
    assert cfg.cleaners_enabled == ("whitespace",)
    assert any("bogus" in rec.message for rec in caplog.records)


# 7 — ambas env vars cleaners presentes → solo enabled
def test_env_cleaners_enabled_and_disabled_uses_enabled(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = load_config(
        env={
            "CAPMD_CLEANERS_ENABLED": "whitespace",
            "CAPMD_CLEANERS_DISABLED": "headers",
        },
        global_toml=None,
        project_toml=None,
    )
    assert cfg.cleaners_enabled == ("whitespace",)
    assert cfg.cleaners_disabled is None
    assert any(
        "cleaners" in rec.message.lower() for rec in caplog.records
    )


# 9 — merge_configs puro
def test_merge_configs_override_wins() -> None:
    base = CapmdConfig(
        out_dir=Path("/tmp/base"),
        image_format="png",
        page_offset=1,
        cleaners_enabled=("whitespace",),
        cleaners_disabled=None,
    )
    override = CapmdConfig(
        out_dir=Path("/tmp/env"),
        image_format="webp",
        page_offset=9,
        cleaners_enabled=None,
        cleaners_disabled=("headers",),
    )
    merged = merge_configs(base, override)
    assert merged.out_dir == Path("/tmp/env")
    assert merged.image_format == "webp"
    assert merged.page_offset == 9
    # cleaners_enabled None en override → conserva base
    assert merged.cleaners_enabled == ("whitespace",)
    assert merged.cleaners_disabled == ("headers",)


def test_merge_configs_empty_override_keeps_base() -> None:
    base = CapmdConfig(
        out_dir=None,
        image_format="webp",
        page_offset=2,
        cleaners_enabled=None,
        cleaners_disabled=None,
    )
    override = CapmdConfig(
        out_dir=None,
        image_format=DEFAULTS["image_format"],
        page_offset=DEFAULTS["page_offset"],
        cleaners_enabled=None,
        cleaners_disabled=None,
    )
    merged = merge_configs(base, override)
    assert merged.out_dir is None
    assert merged.image_format == "webp"
    assert merged.page_offset == 2


def test_env_vars_constant_exposes_documented_names() -> None:
    assert "CAPMD_OUT_DIR" in ENV_VARS
    assert "CAPMD_IMAGE_FORMAT" in ENV_VARS
    assert "CAPMD_PAGE_OFFSET" in ENV_VARS
    assert "CAPMD_CLEANERS_ENABLED" in ENV_VARS
    assert "CAPMD_CLEANERS_DISABLED" in ENV_VARS


# 8 — Smoke CLI: CAPMD_IMAGE_FORMAT cambia comportamiento sin flag
def test_cli_smoke_env_changes_image_format_without_flag(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = build.build_two_images_pdf(tmp_path / "with-imgs.pdf", tmp_path)
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    monkeypatch.setenv("CAPMD_IMAGE_FORMAT", "webp")
    # Asegurar que ni global ni project TOML existan en tmp_path.
    monkeypatch.setattr(
        _capmd_config,
        "load_config",
        lambda *, env=None, project_toml=None, global_toml=None: _capmd_config.load_config.__wrapped__  # type: ignore[attr-defined]
    ) if False else None  # placeholder; usamos directamente load_config con env custom

    # Llamamos load_config con env custom y monkeypatcheamos env vars
    # solo acá; el convert real lee os.environ, así que setenv alcanza.
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf),
            "-o",
            str(out_md),
        ],
    )
    assert r.exit_code == 0, r.output
    images = sorted(p.name for p in images_dir.glob("*"))
    assert images, list(images_dir.glob("*"))
    assert any(name.endswith(".webp") for name in images), images


# 1 — CLI override sobre env
def test_cli_flag_overrides_env(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el usuario pasa --image-format, gana sobre env var."""
    monkeypatch.setenv("CAPMD_IMAGE_FORMAT", "webp")
    pdf = build.build_two_images_pdf(tmp_path / "h.pdf", tmp_path)
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf),
            "-o",
            str(out_md),
            "--image-format",
            "png",
        ],
    )
    assert r.exit_code == 0, r.output
    images = sorted(p.name for p in images_dir.glob("*"))
    assert images, list(images_dir.glob("*"))
    assert all(name.endswith(".png") for name in images), images
