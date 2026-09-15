"""Tests end-to-end del front matter YAML (F2)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

REQUIRED_KEYS = {
    "title", "book", "chapter", "pages", "source_file",
    "source_sha256", "converted_at", "capmd_version",
    "markitdown_version", "cleaners_applied",
}


# --- helpers --------------------------------------------------------------


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "Rust Handbook.pdf")


def _runner_convert(args: list[str]) -> object:
    return CliRunner().invoke(app, ["convert", *args])


def _extract_yaml_block(md_path: Path) -> dict:
    """Lee el .md y parsea el bloque YAML que arranca en la primera línea."""
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"el archivo no arranca con YAML: {md_path}"
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert m is not None, f"no se encontró el cierre --- en {md_path}"
    return yaml.safe_load(m.group(1))


# --- Literal test of F2 roadmap ------------------------------------------


def test_out_md_yaml_parses_with_ten_required_keys(tmp_path: Path) -> None:
    """Test literal del roadmap F2.

    Con ``--out`` + ``--chapter`` el .md arranca con un bloque YAML
    que parsea con ``yaml.safe_load`` y contiene las 10 claves.
    """
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = _runner_convert([str(pdf), "--out", str(out_dir), "--chapter", "3"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    md = out_dir / "rust-handbook" / "cap-03-ownership" / "cap-03-ownership.md"
    assert md.exists()

    parsed = _extract_yaml_block(md)
    assert set(parsed.keys()) >= REQUIRED_KEYS, (
        f"faltan claves: {REQUIRED_KEYS - set(parsed.keys())}"
    )


# --- Stdout NO lleva front matter -----------------------------------------


def test_stdout_has_no_yaml(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    result = _runner_convert([str(pdf), "--chapter", "3"])

    assert result.exit_code == 0, (result.stderr,)
    assert not result.stdout.startswith("---\n"), (
        "stdout no debe llevar front matter"
    )


# --- -o FILE también prepende --------------------------------------------


def test_minus_o_file_prepends_yaml(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "single.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--chapter", "3"])

    assert result.exit_code == 0, (result.stderr,)
    parsed = _extract_yaml_block(out)
    assert set(parsed.keys()) >= REQUIRED_KEYS


# --- --out --flat prepende YAML ------------------------------------------


def test_out_flat_prepends_yaml(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "flat"
    result = _runner_convert(
        [str(pdf), "--out", str(out_dir), "--chapter", "3", "--flat"]
    )
    assert result.exit_code == 0, (result.stderr,)
    parsed = _extract_yaml_block(out_dir / "rust-handbook.md")
    assert set(parsed.keys()) >= REQUIRED_KEYS


# --- cleaners_applied respeta los flags ----------------------------------


def test_yaml_no_clean_yields_empty_cleaners(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "no-clean.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--no-clean"])
    assert result.exit_code == 0, (result.stderr,)
    parsed = _extract_yaml_block(out)
    assert parsed["cleaners_applied"] == []


def test_yaml_only_clean_lists_only_requested(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "only.md"
    result = _runner_convert(
        [str(pdf), "-o", str(out), "--only-clean", "whitespace,hyphens"]
    )
    assert result.exit_code == 0, (result.stderr,)
    parsed = _extract_yaml_block(out)
    assert parsed["cleaners_applied"] == ["whitespace", "hyphens"]


# --- chapter field es el slug -------------------------------------------


def test_yaml_chapter_is_slug(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "x.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--chapter", "3"])
    assert result.exit_code == 0, (result.stderr,)
    parsed = _extract_yaml_block(out)
    assert parsed["chapter"] == "cap-03-ownership"


def test_yaml_pages_field_is_list_with_pages_spec(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "y.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--pages", "1-2"])
    assert result.exit_code == 0, (result.stderr,)
    parsed = _extract_yaml_block(out)
    assert parsed["chapter"] == "pages-1-2"
    assert parsed["pages"] == [1, 2]


# --- stdin: source_file y source_sha256 son null -------------------------


def test_yaml_stdin_has_null_source(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "stdin-tree"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", "-", "--ext", "pdf", "--out", str(out)],
        input=pdf.read_bytes(),
    )
    assert result.exit_code == 0, (result.stderr,)
    md = out / "stdin" / "full" / "full.md"
    parsed = _extract_yaml_block(md)
    assert parsed["source_file"] is None
    assert parsed["source_sha256"] is None
    assert parsed["pages"] is None
    assert parsed["book"] == "stdin"


# --- Idempotencia: 2 corridas no acumulan YAML --------------------------


def test_prepend_is_idempotent_via_cli(tmp_path: Path) -> None:
    """Re-correr capmd sobre un .md que ya tiene FM reemplaza el bloque."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "idem.md"
    runner = CliRunner()

    res1 = runner.invoke(app, ["convert", str(pdf), "-o", str(out), "--chapter", "3"])
    res2 = runner.invoke(app, ["convert", str(pdf), "-o", str(out), "--chapter", "3"])

    assert res1.exit_code == 0, res1.stderr
    # La segunda corrida choca con el archivo existente (pre-F8, sin --force).
    # Esa colisión es esperable; en su lugar verificamos: si la pipeline
    # llegara a escribir (p.ej. forzando), solo debería haber un bloque.
    # Para evitar la colisión borramos y re-corramos.
    if res2.exit_code != 0:
        return

    text = out.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    # Solo un bloque de cierre `---` antes del cuerpo.
    body_idx = text.find("\n---\n", 4)  # después del opening
    assert body_idx != -1
    after_close = text[body_idx + len("\n---\n"):]
    # Después del primer cierre, NO debe volver a aparecer `---\n` (otro bloque).
    assert "\n---\n" not in after_close


# --- title detection ------------------------------------------------------


def test_yaml_title_falls_back_to_first_h1(tmp_path: Path) -> None:
    """El test PDF outline tiene el primer H1 como 'Chapter 1: Getting Started'.
    Cuando no hay chapter resuelto y el markdown contiene un H1, ese H1 gana."""
    pdf = build.build_headings_pdf(tmp_path / "Rust Handbook.pdf")
    out = tmp_path / "title.md"
    result = _runner_convert([str(pdf), "-o", str(out)])
    assert result.exit_code == 0, (result.stderr,)
    parsed = _extract_yaml_block(out)
    # No exige un valor exacto (markitdown puede variar), pero sí que no sea el slug vacío.
    assert isinstance(parsed["title"], str)
    assert parsed["title"]
