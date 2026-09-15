"""Tests e2e de sobrescritura segura (F8)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# --- helpers --------------------------------------------------------------


def _normal_pdf(tmp_path: Path) -> Path:
    return build.build_headings_pdf(tmp_path / "Rust Handbook.pdf")


def _convert(args: list[str]) -> object:
    return CliRunner().invoke(app, ["convert", *args])


# --- Literal test del roadmap F8 ------------------------------------------


def test_second_run_without_force_exits_with_clear_message(tmp_path: Path) -> None:
    """Test literal F8: 2da corrida sin flags → exit ≠ 0 + mensaje claro."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out"
    r1 = _convert([str(pdf), "--out", str(out)])
    assert r1.exit_code == 0, r1.stderr
    assert out.exists()

    r2 = _convert([str(pdf), "--out", str(out)])
    assert r2.exit_code == 7, (
        f"esperaba exit 7 (IOError de F1), recibí {r2.exit_code}"
    )
    err = r2.stderr.lower()
    assert "ya existe" in err
    assert "--force" in err
    assert "--suffix" in err


# --- --force ---------------------------------------------------------------


def test_force_overwrites_existing_destination(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out"
    _convert([str(pdf), "--out", str(out)])

    # 2da corrida con --force sobrescribe sin error.
    r2 = _convert([str(pdf), "--out", str(out), "--force"])
    assert r2.exit_code == 0, r2.stderr
    assert out.exists()
    # El chapter dir sigue presente.
    chapter_dirs = list(out.rglob("full.md"))
    assert len(chapter_dirs) == 1


# --- --suffix -------------------------------------------------------------


def test_suffix_creates_versioned_chapter_dir(tmp_path: Path) -> None:
    """``--suffix`` versiona el chapter_dir raíz (``<out>/<book>/<chapter>-1/``)."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out"
    r1 = _convert([str(pdf), "--out", str(out)])
    assert r1.exit_code == 0, r1.stderr
    original_chapter = out / "rust-handbook" / "full"
    assert original_chapter.exists()

    # 2da corrida con --suffix crea ``<out>/<book>/<chapter>-1/``.
    r2 = _convert([str(pdf), "--out", str(out), "--suffix"])
    assert r2.exit_code == 0, r2.stderr
    versioned = out / "rust-handbook" / "full-1"
    assert versioned.exists(), f"{versioned} no se creó"
    # La original sigue intacta.
    assert original_chapter.exists()
    assert (original_chapter / "full.md").exists()
    # El versionado usa el chapter_slug versionado como filename.
    assert (versioned / "full-1.md").exists()
    assert (versioned / "capmd.json").exists()


def test_suffix_chains_multiple_versions(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out"
    _convert([str(pdf), "--out", str(out)])
    _convert([str(pdf), "--out", str(out), "--suffix"])
    r3 = _convert([str(pdf), "--out", str(out), "--suffix"])
    assert r3.exit_code == 0, r3.stderr
    assert (out / "rust-handbook" / "full-2").exists()


def test_suffix_with_minus_o_file(tmp_path: Path) -> None:
    """``-o FILE --suffix`` crea ``<stem>-1.md``."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "single.md"
    _convert([str(pdf), "-o", str(out)])
    r2 = _convert([str(pdf), "-o", str(out), "--suffix"])
    assert r2.exit_code == 0, r2.stderr
    assert out.exists()
    assert (tmp_path / "single-1.md").exists()


# --- Validation ----------------------------------------------------------


def test_force_and_suffix_together_errors(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out"
    r = _convert([str(pdf), "--out", str(out), "--force", "--suffix"])
    assert r.exit_code == 2, r.stderr
    assert "force" in r.stderr.lower() and "suffix" in r.stderr.lower()


# --- Compatibilidad con flags existentes ----------------------------------


def test_force_with_flat_overwrites(tmp_path: Path) -> None:
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "flat_dir"
    _convert([str(pdf), "--out", str(out), "--flat"])
    r2 = _convert([str(pdf), "--out", str(out), "--flat", "--force"])
    assert r2.exit_code == 0, r2.stderr
    flat_file = out / "rust-handbook.md"
    assert flat_file.exists()


def test_suffix_with_split_h2(tmp_path: Path) -> None:
    """``--split h2 --suffix`` versiona el chapter_dir completo."""
    pdf = build.build_four_h2_pdf(tmp_path / "Rust Handbook.pdf")
    out = tmp_path / "split_out"
    _convert([str(pdf), "--out", str(out), "--split", "h2"])
    r2 = _convert([str(pdf), "--out", str(out), "--split", "h2", "--suffix"])
    assert r2.exit_code == 0, r2.stderr
    # El chapter_dir original (`<book>/<chapter>/`) tiene su `sections/`.
    chapter_dirs = list((out / "rust-handbook").iterdir())
    assert len(chapter_dirs) >= 2, (
        f"esperaba >=2 chapter_dirs en rust-handbook/, encontré {chapter_dirs}"
    )
    # El versionado contiene `full-N.md` + `sections/`.
    versioned = next(d for d in chapter_dirs if d.name.endswith("-1"))
    assert (versioned / "full-1.md").exists()
    assert (versioned / "sections").exists()


def test_keep_raw_snapshot_unaffected(tmp_path: Path) -> None:
    """``--keep-raw`` no entra en la lógica de overwrite (F8)."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "x.md"
    _convert([str(pdf), "-o", str(out), "--keep-raw"])
    # Segunda corrida CON --force para que no falle la colisión.
    r2 = _convert([str(pdf), "-o", str(out), "--keep-raw", "--force"])
    assert r2.exit_code == 0, r2.stderr
    # La snapshot del .capmd/raw.md se sobreescribió (sin error).
    assert (tmp_path / ".capmd" / "raw.md").exists()


# --- Help -----------------------------------------------------------------


def test_help_mentions_force_and_suffix() -> None:
    r = CliRunner().invoke(app, ["convert", "--help"])
    assert r.exit_code == 0
    assert "--force" in r.stdout
    assert "--suffix" in r.stdout
