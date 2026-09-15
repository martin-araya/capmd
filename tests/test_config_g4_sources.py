"""Tests para G4 — sources tracking (helper de ``capmd config show``)."""

from __future__ import annotations

from pathlib import Path

from capmd.config import (
    SRC_DEFAULT,
    SRC_ENV,
    SRC_GLOBAL,
    SRC_PROJECT,
    CapmdConfig,
    apply_book_profile,
    find_profile_by_name,
    load_config,
    merge_configs,
)
from capmd.llm import DEFAULT_MODELS as _LMDM  # noqa: F401  -- not used


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_sources_are_default_when_no_toml(tmp_path: Path) -> None:
    cfg = load_config(
        env={},
        global_toml=tmp_path / "no-global.toml",
        project_toml=tmp_path / "no-project.toml",
    )
    assert all(v == SRC_DEFAULT for v in cfg.sources.values())


def test_sources_track_global_toml(tmp_path: Path) -> None:
    global_ = tmp_path / "global.toml"
    _write_toml(global_, "page_offset = 1\nimage_format = \"webp\"\nout_dir = \"/tmp/g\"\n")
    cfg = load_config(
        env={},
        global_toml=global_,
        project_toml=tmp_path / "no-project.toml",
    )
    # Las claves presentes en global deben atribuirse a global; las
    # ausentes a default. ``cleaners_*`` e ``image_overrides`` están
    # en default porque no se setearon.
    assert cfg.sources["page_offset"] == SRC_GLOBAL
    assert cfg.sources["image_format"] == SRC_GLOBAL
    assert cfg.sources["out_dir"] == SRC_GLOBAL
    assert cfg.sources["cleaners_enabled"] == SRC_DEFAULT


def test_sources_track_project_toml(tmp_path: Path) -> None:
    project = tmp_path / "capmd.toml"
    _write_toml(project, "page_offset = 1\nimage_format = \"webp\"\nout_dir = \"/tmp/p\"\n")
    cfg = load_config(
        env={},
        global_toml=tmp_path / "no-global.toml",
        project_toml=project,
    )
    assert cfg.sources["page_offset"] == SRC_PROJECT
    assert cfg.sources["image_format"] == SRC_PROJECT
    assert cfg.sources["out_dir"] == SRC_PROJECT
    assert cfg.sources["cleaners_enabled"] == SRC_DEFAULT


def test_per_key_attribution_global_only(tmp_path: Path) -> None:
    """Sólo la clave presente en global tiene source=global; las demás
    son default."""
    global_ = tmp_path / "global.toml"
    _write_toml(global_, "page_offset = 5\n")
    cfg = load_config(env={}, global_toml=global_, project_toml=None)
    assert cfg.sources["page_offset"] == SRC_GLOBAL
    assert cfg.sources["image_format"] == SRC_DEFAULT


def test_per_key_attribution_project_overrides_global(tmp_path: Path) -> None:
    global_ = tmp_path / "global.toml"
    project = tmp_path / "capmd.toml"
    _write_toml(global_, "page_offset = 1\nimage_format = \"webp\"\n")
    _write_toml(project, "page_offset = 9\n")
    cfg = load_config(env={}, global_toml=global_, project_toml=project)
    # page_offset: solo en ambos → project gana attribution.
    assert cfg.sources["page_offset"] == SRC_PROJECT
    # image_format: solo global → source=global.
    assert cfg.sources["image_format"] == SRC_GLOBAL


def test_sources_track_env_override(tmp_path: Path) -> None:
    cfg = load_config(
        env={"CAPMD_PAGE_OFFSET": "5"},
        global_toml=tmp_path / "no-global.toml",
        project_toml=tmp_path / "no-project.toml",
    )
    assert cfg.sources["page_offset"] == SRC_ENV
    assert cfg.sources["image_format"] == SRC_DEFAULT


def test_book_profile_attribution(tmp_path: Path) -> None:
    toml = tmp_path / "capmd.toml"
    _write_toml(toml, '[books."x"]\npage_offset = 7\n')
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    assert cfg.sources["page_offset"] == SRC_DEFAULT  # no está en project top-level
    profile = find_profile_by_name(cfg.books, "x")
    assert profile is not None
    final = apply_book_profile(cfg, profile)
    assert final.sources["page_offset"] == "book:x"
    # Otros campos mantienen su source anterior.
    assert final.sources["image_format"] == SRC_DEFAULT


def test_merge_configs_combines_sources() -> None:
    a = CapmdConfig(
        out_dir=None,
        image_format="png",
        page_offset=0,
        cleaners_enabled=None,
        cleaners_disabled=None,
        sources={"out_dir": SRC_DEFAULT, "page_offset": SRC_DEFAULT},
    )
    b = CapmdConfig(
        out_dir=Path("/x"),
        image_format="webp",
        page_offset=5,
        cleaners_enabled=None,
        cleaners_disabled=None,
        sources={
            "out_dir": SRC_ENV,
            "page_offset": SRC_ENV,
            "image_format": SRC_ENV,
        },
    )
    merged = merge_configs(a, b)
    assert merged.sources["out_dir"] == SRC_ENV
    assert merged.sources["image_format"] == SRC_ENV
    assert merged.sources["page_offset"] == SRC_ENV
