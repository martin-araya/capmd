"""Tests para G1 — Config TOML global en `~/.config/capmd/config.toml`.

Cubre el test del roadmap: "un valor del TOML cambia el comportamiento
sin pasar flags". En concreto: ``load_config()`` devuelve ``CapmdConfig``
con defaults aplicados; la CLI los usa cuando el flag correspondiente
no se pasa.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.clean.pipeline import available_cleaner_names
from capmd.cli import app
from capmd.config import CapmdConfig, load_config, load_image_filter_overrides
from tests.fixtures import build


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _names(pipeline) -> list[str]:
    return [c.name for c in pipeline.cleaners]


# 1
def test_global_toml_out_dir_is_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "from_global"
    cfg_toml = tmp_path / "capmd-config" / "config.toml"
    _write_toml(
        cfg_toml,
        f'out_dir = "{target.as_posix()}"\n',
    )
    cfg = load_config(
        global_toml=cfg_toml,
        project_toml=tmp_path / "capmd.toml",
    )
    assert cfg.out_dir == target
    assert cfg_toml in cfg.source_paths


# 2
def test_global_toml_image_format_changes_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_toml = tmp_path / "global.toml"
    _write_toml(cfg_toml, 'image_format = "webp"\n')
    cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.image_format == "webp"


# 3
def test_global_toml_page_offset_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_toml = tmp_path / "global.toml"
    _write_toml(cfg_toml, "page_offset = 2\n")
    cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.page_offset == 2


# 4
def test_global_toml_cleaners_disabled_removes_from_pipeline(
    tmp_path: Path,
) -> None:
    from capmd.clean.pipeline import default_pipeline, filter_pipeline

    cfg_toml = tmp_path / "global.toml"
    _write_toml(
        cfg_toml,
        '[cleaners]\ndisabled = ["page_numbers"]\n',
    )
    cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.cleaners_disabled == ("page_numbers",)
    assert cfg.cleaners_enabled is None

    base = default_pipeline()
    assert "page_numbers" in _names(base)
    if cfg.cleaners_disabled is not None:
        filtered = filter_pipeline(base, skip=cfg.cleaners_disabled)
    else:
        filtered = base
    assert "page_numbers" not in _names(filtered)


# 5
def test_global_toml_cleaners_enabled_whitelist(tmp_path: Path) -> None:
    from capmd.clean.pipeline import default_pipeline, filter_pipeline

    cfg_toml = tmp_path / "global.toml"
    _write_toml(
        cfg_toml,
        '[cleaners]\nenabled = ["whitespace", "headers"]\n',
    )
    cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.cleaners_enabled == ("whitespace", "headers")

    base = default_pipeline()
    if cfg.cleaners_enabled is not None:
        filtered = filter_pipeline(base, only=cfg.cleaners_enabled)
    else:
        filtered = base
    assert _names(filtered) == ["whitespace", "headers"]


# 6
def test_project_overrides_global(tmp_path: Path) -> None:
    global_toml = tmp_path / "global" / "config.toml"
    project_toml = tmp_path / "capmd.toml"
    _write_toml(global_toml, "page_offset = 2\nimage_format = \"webp\"\n")
    _write_toml(project_toml, "page_offset = 5\n")
    cfg = load_config(global_toml=global_toml, project_toml=project_toml)
    assert cfg.page_offset == 5
    assert cfg.image_format == "webp"


# 7
def test_project_only_used_when_present(tmp_path: Path) -> None:
    global_toml = tmp_path / "global.toml"
    _write_toml(global_toml, 'image_format = "webp"\n')
    cfg = load_config(
        global_toml=global_toml,
        project_toml=tmp_path / "missing.toml",
    )
    assert cfg.image_format == "webp"
    assert global_toml in cfg.source_paths


# 8
def test_invalid_image_format_falls_back_to_png(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg_toml = tmp_path / "global.toml"
    _write_toml(cfg_toml, 'image_format = "gif"\n')
    with caplog.at_level(logging.WARNING):
        cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.image_format == "png"
    assert any("image_format" in rec.message for rec in caplog.records)


# 9
def test_invalid_page_offset_falls_back_to_zero(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg_toml = tmp_path / "global.toml"
    _write_toml(cfg_toml, "page_offset = -1\n")
    with caplog.at_level(logging.WARNING):
        cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.page_offset == 0
    assert any("page_offset" in rec.message for rec in caplog.records)


# 10
def test_malformed_toml_does_not_crash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg_toml = tmp_path / "global.toml"
    cfg_toml.write_text("this is not = valid toml [[[", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg == CapmdConfig(
        out_dir=None,
        image_format="png",
        page_offset=0,
        cleaners_enabled=None,
        cleaners_disabled=None,
        image_overrides={},
        source_paths=(),
        sources={
            "out_dir": "default",
            "image_format": "default",
            "page_offset": "default",
            "cleaners_enabled": "default",
            "cleaners_disabled": "default",
            "image_overrides": "default",
        },
    )


# 11
def test_cleaners_enabled_and_disabled_both_present_uses_enabled(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg_toml = tmp_path / "global.toml"
    _write_toml(
        cfg_toml,
        (
            "[cleaners]\n"
            'enabled = ["whitespace"]\n'
            'disabled = ["headers"]\n'
        ),
    )
    with caplog.at_level(logging.WARNING):
        cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.cleaners_enabled == ("whitespace",)
    assert cfg.cleaners_disabled is None
    assert any(
        "enabled y disabled" in rec.message or "enabled" in rec.message
        for rec in caplog.records
    )


# 12
def test_cli_smoke_no_toml_unchanged_behavior(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin TOML en disco, defaults idénticos a los del comportamiento previo."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config(
        global_toml=tmp_path / "no-config.toml",
        project_toml=tmp_path / "no-project.toml",
    )
    assert cfg.out_dir is None
    assert cfg.image_format == "png"
    assert cfg.page_offset == 0
    assert cfg.cleaners_enabled is None
    assert cfg.cleaners_disabled is None

    # Y `capmd convert --help` sigue funcionando sin warnings nuevos.
    r = runner.invoke(app, ["convert", "--help"])
    assert r.exit_code == 0
    assert "--image-format" in r.output


# 13
def test_cli_smoke_global_toml_changes_image_format_without_flag(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test end-to-end del roadmap: TOML global cambia comportamiento
    sin pasar flag --image-format."""
    from capmd import config as _capmd_config
    from capmd.config import load_config as _load

    cfg_toml = tmp_path / "global.toml"
    _write_toml(cfg_toml, 'image_format = "webp"\n')

    # Patch load_config en el MÓDULO (no en cli) para que la resolución
    # del CLI (que importa ``capmd.config`` como módulo y llama
    # ``load_config()`` por atributo) vea el override.
    def _patched_load_config(
        *,
        project_toml=None,
        global_toml=None,
    ) -> CapmdConfig:
        return _load(global_toml=cfg_toml)

    monkeypatch.setattr(_capmd_config, "load_config", _patched_load_config)

    pdf = build.build_two_images_pdf(tmp_path / "with-imgs.pdf", tmp_path)
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"
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
    assert out_md.exists()
    images = sorted(p.name for p in images_dir.glob("*"))
    assert images, list(images_dir.glob("*"))
    assert any(name.endswith(".webp") for name in images), images


def test_load_image_filter_overrides_compat_shim(tmp_path: Path) -> None:
    """API vieja de E2 sigue viva y devuelve las claves conocidas."""
    cfg_toml = tmp_path / "global.toml"
    _write_toml(
        cfg_toml,
        (
            "[images]\n"
            'min_size = "128x128"\n'
            'repeat_threshold = 0.5\n'
            "background_coverage = 0.9\n"
            "bogus = 1\n"  # clave desconocida: ignorada
        ),
    )
    overrides = load_image_filter_overrides(global_toml=cfg_toml)
    cfg = load_config(global_toml=cfg_toml, project_toml=None)
    assert cfg.image_overrides == overrides
    assert "bogus" not in cfg.image_overrides


def test_available_cleaner_names_dynload(tmp_path: Path) -> None:
    names = set(available_cleaner_names())
    assert "whitespace" in names
    assert "headers" in names
    # no se repiten
    assert len(names) == len(available_cleaner_names())
