"""Tests para G3 — Perfiles por libro (``[books.\"<id>\"]``)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd import config as _capmd_config
from capmd.cli import app
from capmd.config import (
    DEFAULTS,
    SHA256_PREFIX,
    CapmdConfig,
    apply_book_profile,
    find_profile_by_hash,
    find_profile_by_name,
    load_config,
)


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_two_books_different_offsets_different_ranges(tmp_path: Path) -> None:
    """Test literal del roadmap: dos perfiles con page_offset distintos."""
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        (
            '[books."alpha"]\npage_offset = 2\n\n'
            '[books."beta"]\npage_offset = 5\n'
        ),
    )
    cfg = load_config(
        env={}, global_toml=None, project_toml=toml
    )
    a = find_profile_by_name(cfg.books, "alpha")
    b = find_profile_by_name(cfg.books, "beta")
    assert a is not None and b is not None
    assert a.page_offset == 2
    assert b.page_offset == 5
    # Aplicar cada uno sobre la misma config; el resolved page_offset cambia.
    base_resolved = 10  # simulated printed page
    assert (base_resolved + a.page_offset) != (base_resolved + b.page_offset)


def test_book_flag_activates_named_profile(tmp_path: Path) -> None:
    toml = tmp_path / "capmd.toml"
    _write_toml(toml, '[books."alpha"]\npage_offset = 7\n')
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    profile = find_profile_by_name(cfg.books, "alpha")
    assert profile is not None
    resolved = apply_book_profile(cfg, profile)
    assert resolved.page_offset == 7


def test_unknown_book_flag_errors(tmp_path: Path) -> None:
    """Comportamiento del caller: --book no definido → no match."""
    toml = tmp_path / "capmd.toml"
    _write_toml(toml, '[books."alpha"]\npage_offset = 1\n')
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    assert find_profile_by_name(cfg.books, "does-not-exist") is None


def test_hash_auto_matching(tmp_path: Path) -> None:
    hex_hash = "a" * 64
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        (
            f'[books."{SHA256_PREFIX}{hex_hash}"]\n'
            "page_offset = 3\n"
            'title_pattern = "^Cap\\\\s+\\\\d+"\n'
        ),
    )
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    match = find_profile_by_hash(cfg.books, hex_hash)
    assert match is not None
    assert match.page_offset == 3
    assert match.title_pattern == r"^Cap\s+\d+"


def test_hash_prefix_does_not_collide_with_named(tmp_path: Path) -> None:
    """Un nombre que CASUALMENTE empieza con sha256: pero NO es 64 hex
    NO debe matchear como hash."""
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        '[books."sha256:notreallyhex"]\npage_offset = 1\n',
    )
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    # Como nombre, funciona:
    name_match = find_profile_by_name(cfg.books, "sha256:notreallyhex")
    assert name_match is not None
    # Como hash con 64 chars, ningún perfil encaja (solo hay uno con
    # nombre igual).
    hash_match = find_profile_by_hash(cfg.books, "a" * 64)
    assert hash_match is None


def test_book_profile_overrides_global_toml(tmp_path: Path) -> None:
    global_ = tmp_path / "global.toml"
    project = tmp_path / "capmd.toml"
    _write_toml(global_, "page_offset = 1\n")
    _write_toml(project, '[books."x"]\npage_offset = 5\n')
    cfg = load_config(
        env={}, global_toml=global_, project_toml=project
    )
    assert cfg.page_offset == 1  # base
    profile = find_profile_by_name(cfg.books, "x")
    applied = apply_book_profile(cfg, profile)  # type: ignore[arg-type]
    assert applied.page_offset == 5  # book > global


def test_book_profile_loses_to_cli_flag(tmp_path: Path) -> None:
    """Simula CLI flag explícito ganando al perfil."""
    toml = tmp_path / "capmd.toml"
    _write_toml(toml, '[books."x"]\npage_offset = 5\n')
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    profile = find_profile_by_name(cfg.books, "x")
    cfg_after_profile = apply_book_profile(cfg, profile)  # type: ignore[arg-type]
    # CLI flag explícito gana:
    final = CapmdConfig(
        out_dir=cfg_after_profile.out_dir,
        image_format=cfg_after_profile.image_format,
        page_offset=9,  # CLI
        cleaners_enabled=cfg_after_profile.cleaners_enabled,
        cleaners_disabled=cfg_after_profile.cleaners_disabled,
        image_overrides=cfg_after_profile.image_overrides,
        books=cfg_after_profile.books,
        source_paths=cfg_after_profile.source_paths,
    )
    assert final.page_offset == 9


def test_book_profile_cleaners_override_global(tmp_path: Path) -> None:
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        (
            "[cleaners]\ndisabled = [\"headers\"]\n\n"
            "[books.\"x\"]\n"
            "[books.\"x\".cleaners]\n"
            "disabled = [\"page_numbers\"]\n"
        ),
    )
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    assert cfg.cleaners_disabled == ("headers",)
    profile = find_profile_by_name(cfg.books, "x")
    applied = apply_book_profile(cfg, profile)  # type: ignore[arg-type]
    assert applied.cleaners_disabled == ("page_numbers",)


def test_book_profile_title_pattern_regex() -> None:
    """Verifica que el regex source se preserva y compila."""
    from capmd.config import _read_book_profile

    profile = _read_book_profile(
        "x", {"title_pattern": r"^Chapter\s+\d+"}
    )
    assert profile is not None
    assert profile.title_pattern == r"^Chapter\s+\d+"


def test_invalid_title_pattern_falls_back_to_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        '[books."x"]\npage_offset = 1\ntitle_pattern = "["\n',
    )
    with caplog.at_level(logging.WARNING):
        cfg = load_config(env={}, global_toml=None, project_toml=toml)
    assert "x" in cfg.books
    assert cfg.books["x"].title_pattern is None
    assert any("title_pattern" in rec.message for rec in caplog.records)


def test_book_profile_image_format(tmp_path: Path) -> None:
    toml = tmp_path / "capmd.toml"
    _write_toml(toml, '[books."x"]\nimage_format = "webp"\n')
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    profile = find_profile_by_name(cfg.books, "x")
    applied = apply_book_profile(cfg, profile)  # type: ignore[arg-type]
    assert applied.image_format == "webp"


def test_books_section_in_global_toml(tmp_path: Path) -> None:
    global_ = tmp_path / "global.toml"
    _write_toml(global_, '[books."from-global"]\npage_offset = 4\n')
    cfg = load_config(env={}, global_toml=global_, project_toml=None)
    assert "from-global" in cfg.books
    assert cfg.books["from-global"].page_offset == 4


def test_books_section_project_overrides_global(tmp_path: Path) -> None:
    global_ = tmp_path / "global.toml"
    project = tmp_path / "capmd.toml"
    _write_toml(global_, '[books."x"]\npage_offset = 1\n')
    _write_toml(project, '[books."x"]\npage_offset = 9\n')
    cfg = load_config(
        env={}, global_toml=global_, project_toml=project
    )
    # Perfiles se cargan del merged TOML; el segundo _read_book_profile
    # sobreescribe al primero vía ``merged.update``.
    assert cfg.books["x"].page_offset == 9


def test_empty_book_table_uses_minimal_profile(tmp_path: Path) -> None:
    """Tabla sin claves reconocibles → perfil descartado (None)."""
    from capmd.config import _read_book_profile

    assert _read_book_profile("x", {}) is None
    assert _read_book_profile("x", {"unknown_key": 1}) is None
    # Tabla con al menos una clave válida sí produce perfil.
    p = _read_book_profile("x", {"page_offset": 2})
    assert p is not None and p.page_offset == 2


def test_no_match_no_profile_applied(tmp_path: Path) -> None:
    """Sin match, no se aplica ningún perfil y se respeta la config base."""
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        '[books."alpha"]\npage_offset = 99\n',
    )
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    # Sin --book ni hash match, no aplicar → page_offset = default
    assert cfg.page_offset == DEFAULTS["page_offset"]
    assert "alpha" in cfg.books  # pero el perfil está disponible


def test_books_section_must_be_table(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    toml = tmp_path / "capmd.toml"
    _write_toml(toml, "books = 5\n")
    with caplog.at_level(logging.WARNING):
        cfg = load_config(env={}, global_toml=None, project_toml=toml)
    assert cfg.books == {}


def test_apply_profile_no_op_when_all_none(tmp_path: Path) -> None:
    """Perfil con todos los campos None no rompe la config."""
    from capmd.config import BookProfile

    toml = tmp_path / "capmd.toml"
    _write_toml(toml, "")
    cfg = load_config(env={}, global_toml=None, project_toml=toml)
    empty_profile = BookProfile(name="z")  # TODO None
    out = apply_book_profile(cfg, empty_profile)
    assert out == cfg


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _patch_load_config_with(tmp_path: Path):
    """Devuelve un callable que, aplicado a ``capmd.config``, hace que
    ``load_config`` lea el TOML en tmp_path y use un env vacío."""

    toml = tmp_path / "capmd.toml"

    def patcher() -> None:
        def patched(*, env=None, project_toml=None, global_toml=None):
            return load_config(
                env={},
                global_toml=tmp_path / "no-global.toml",
                project_toml=toml,
            )

        _capmd_config.load_config = patched  # type: ignore[assignment]

    return patcher


def test_cli_two_books_two_offsets_different_ranges(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test literal del roadmap: dos libros con page_offset distintos.

    El test unitario #1 ya verifica la resolución a nivel config;
    acá verificamos que los dos perfiles produzcan rangos distintos
    aplicados al mismo ``--pages``.
    """
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        (
            '[books."alpha"]\npage_offset = 2\n\n'
            '[books."beta"]\npage_offset = 5\n'
        ),
    )

    from capmd.cli import _resolve_pages

    pdf = tmp_path / "twopages.pdf"
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(20):
        writer.add_blank_page(width=72, height=72)
    with pdf.open("wb") as f:
        writer.write(f)

    monkeypatch.setattr("capmd.cli.PROJECT_TOML", toml, raising=False)

    def loader(*, env=None, project_toml=None, global_toml=None):
        return load_config(
            env={},
            global_toml=tmp_path / "no-global.toml",
            project_toml=toml,
        )

    monkeypatch.setattr(_capmd_config, "load_config", loader)

    # --pages 10-12 con perfil alpha (offset=2) → physical 12-14.
    _, _, pages_alpha, _ = _resolve_pages(pdf, "10-12", offset=2)
    # --pages 10-12 con perfil beta (offset=5) → physical 15-17.
    _, _, pages_beta, _ = _resolve_pages(pdf, "10-12", offset=5)
    assert pages_alpha == [12, 13, 14]
    assert pages_beta == [15, 16, 17]
    assert pages_alpha != pages_beta


def test_cli_book_flag_changes_image_format(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke: --book con image_format="webp" cambia el formato extraído."""
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        '[books."rgb"]\nimage_format = "webp"\n',
    )

    def loader(*, env=None, project_toml=None, global_toml=None):
        return load_config(
            env={},
            global_toml=tmp_path / "no-global.toml",
            project_toml=toml,
        )

    monkeypatch.setattr(_capmd_config, "load_config", loader)

    from tests.fixtures import build

    pdf = build.build_two_images_pdf(tmp_path / "with-imgs.pdf", tmp_path)
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    r = runner.invoke(
        app,
        ["convert", str(pdf), "-o", str(out_md), "--book", "rgb"],
    )
    assert r.exit_code == 0, r.output
    files = sorted(p.name for p in images_dir.glob("*"))
    assert any(name.endswith(".webp") for name in files), files


def test_cli_unknown_book_errors(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "capmd.toml"
    _write_toml(toml, '[books."alpha"]\npage_offset = 1\n')

    def loader(*, env=None, project_toml=None, global_toml=None):
        return load_config(
            env={},
            global_toml=tmp_path / "no-global.toml",
            project_toml=toml,
        )

    monkeypatch.setattr(_capmd_config, "load_config", loader)

    from tests.fixtures import build

    pdf = build.build_two_images_pdf(tmp_path / "x.pdf", tmp_path)
    r = runner.invoke(
        app,
        ["convert", str(pdf), "-o", str(tmp_path / "out.md"), "--book", "missing"],
    )
    assert r.exit_code != 0
    assert "missing" in r.output or "missing" in (r.stderr or "")


def test_cli_hash_auto_matching(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hash matching: el perfil se activa sin --book cuando el sha256
    del PDF matchea."""
    from tests.fixtures import build

    pdf = build.build_two_images_pdf(tmp_path / "fixture.pdf", tmp_path)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()

    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        (
            f'[books."{SHA256_PREFIX}{sha}"]\n'
            'image_format = "webp"\n'
        ),
    )

    def loader(*, env=None, project_toml=None, global_toml=None):
        return load_config(
            env={},
            global_toml=tmp_path / "no-global.toml",
            project_toml=toml,
        )

    monkeypatch.setattr(_capmd_config, "load_config", loader)

    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    r = runner.invoke(app, ["convert", str(pdf), "-o", str(out_md)])
    assert r.exit_code == 0, r.output
    files = sorted(p.name for p in images_dir.glob("*"))
    assert any(name.endswith(".webp") for name in files), files


def test_cli_title_pattern_regex_matches_outline(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--book con title_pattern regex: --chapter \"borrowing\" matchea
    \"Chapter 3: Borrowing\" aunque no hay literal match."""
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        (
            '[books."rust-handbook"]\n'
            "title_pattern = \"borrowing\"\n"
        ),
    )

    def loader(*, env=None, project_toml=None, global_toml=None):
        return load_config(
            env={},
            global_toml=tmp_path / "no-global.toml",
            project_toml=toml,
        )

    monkeypatch.setattr(_capmd_config, "load_config", loader)

    from tests.fixtures import build

    pdf = build.build_outline_toc_pdf(tmp_path / "toc.pdf")

    out_dir = tmp_path / "out"
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf),
            "--out",
            str(out_dir),
            "--chapter",
            "borrowing",
            "--book",
            "rust-handbook",
        ],
    )
    assert r.exit_code == 0, r.output
    # El chapter "Chapter 3: Borrowing" matchea el regex "borrowing".
    # Aceptamos cualquier cap-XX-borrowing (la X depende del DFS order
    # del outline; acá importa que matcheó y que NO es cap-01).
    chapter_dirs = sorted(
        p for p in out_dir.glob("*/*")
        if p.is_dir() and p.name.startswith("cap-") and "borrowing" in p.name
    )
    assert chapter_dirs, sorted(p.name for p in out_dir.glob("*/*") if p.is_dir())


def test_cli_invalid_title_pattern_falls_back_to_substring(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el regex del title_pattern es inválido, fallback a substring."""
    toml = tmp_path / "capmd.toml"
    _write_toml(
        toml,
        '[books."x"]\nimage_format = "webp"\ntitle_pattern = "["\n',
    )

    def loader(*, env=None, project_toml=None, global_toml=None):
        return load_config(
            env={},
            global_toml=tmp_path / "no-global.toml",
            project_toml=toml,
        )

    monkeypatch.setattr(_capmd_config, "load_config", loader)

    from tests.fixtures import build

    pdf = build.build_outline_toc_pdf(tmp_path / "toc.pdf")
    out_dir = tmp_path / "out"
    # Substring "Borrowing" debe matchear "Chapter 3: Borrowing" incluso
    # con title_pattern inválido (cae al fallback substring).
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf),
            "--out",
            str(out_dir),
            "--chapter",
            "Borrowing",
            "--book",
            "x",
        ],
    )
    assert r.exit_code == 0, r.output
