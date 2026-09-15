"""Tests end-to-end del árbol de salida F1 (``--out`` / ``--flat``)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# --- helpers --------------------------------------------------------------


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "Rust Handbook.pdf")


def _runner_convert(args: list[str]) -> object:
    return CliRunner().invoke(app, ["convert", *args])


# --- Tree layout: --out (the literal test of F1) ---------------------------


def test_out_creates_tree_with_md_images_and_capmd_json(tmp_path: Path) -> None:
    """Test literal del roadmap F1.

    Con ``--out <DIR>`` y ``--chapter 3`` se crea
    ``<DIR>/<book>/cap-03-<title>/{file.md, images/, capmd.json}``.

    El PDF outline usa numeración DFS; la entrada "1.1 Background" se
    cuenta, así que ``--chapter 3`` resuelve a "Chapter 2: Ownership" y
    el slug final es ``cap-03-ownership`` (que es exactamente el del
    ejemplo del roadmap).
    """
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = _runner_convert([str(pdf), "--out", str(out_dir), "--chapter", "3"])

    assert result.exit_code == 0, (result.stdout, result.stderr)

    chapter_dir = out_dir / "rust-handbook" / "cap-03-ownership"
    assert chapter_dir.is_dir(), f"falta el chapter dir: {chapter_dir}"
    md = chapter_dir / "cap-03-ownership.md"
    images = chapter_dir / "images"
    json_path = chapter_dir / "capmd.json"

    assert md.is_file()
    assert md.stat().st_size > 0
    assert images.is_dir()
    assert json_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2  # F3: bumped from 1 to 2
    assert payload["book_slug"] == "rust-handbook"
    assert payload["chapter_slug"] == "cap-03-ownership"
    assert payload["layout"] == "tree"
    assert payload["images_dir"] == "images"
    assert payload["chapter"]["title"] == "Chapter 2: Ownership"
    assert payload["chapter"]["index"] == 3
    assert payload["pages"] == [2]
    # F3: campos nuevos siempre presentes (pueden ser vacíos por default).
    assert "title" in payload
    assert "markitdown_version" in payload
    assert isinstance(payload["cleaner_stats"], list)
    assert isinstance(payload["figures"], list)
    assert payload["warnings"] == []
    assert payload["elapsed_seconds"] >= 0

    # F2: el .md arranca con front matter YAML que parsea con yaml.safe_load
    # y contiene las 10 claves.
    import yaml as _yaml

    md_text = md.read_text(encoding="utf-8")
    assert md_text.startswith("---\n"), "F2: el .md debe arrancar con YAML"
    import re as _re

    fm_match = _re.match(r"\A---\n(.*?)\n---\n", md_text, _re.DOTALL)
    assert fm_match is not None
    fm = _yaml.safe_load(fm_match.group(1))
    assert set(fm.keys()) >= {
        "title", "book", "chapter", "pages", "source_file",
        "source_sha256", "converted_at", "capmd_version",
        "markitdown_version", "cleaners_applied",
    }


def test_out_with_pages_range_uses_pages_slug(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "out2"
    result = _runner_convert([str(pdf), "--out", str(out_dir), "--pages", "1-2"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    chap_dir = out_dir / "rust-handbook" / "pages-1-2"
    assert chap_dir.is_dir()
    payload = json.loads((chap_dir / "capmd.json").read_text(encoding="utf-8"))
    assert payload["chapter_slug"] == "pages-1-2"
    assert payload["range_label"] == "1-2"
    assert payload["chapter"] is None


def test_out_with_chapter_substring_match(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "out3"
    result = _runner_convert([str(pdf), "--out", str(out_dir), "--chapter", "Borrowing"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    # Outline DFS: "Chapter 3: Borrowing" tiene index 4 → cap-04.
    assert (out_dir / "rust-handbook" / "cap-04-borrowing").is_dir()
    payload = json.loads(
        (out_dir / "rust-handbook" / "cap-04-borrowing" / "capmd.json").read_text("utf-8")
    )
    assert payload["chapter"]["title"] == "Chapter 3: Borrowing"


# --- Flat layout: --flat ---------------------------------------------------


def test_flat_writes_only_markdown_no_tree_no_images(tmp_path: Path) -> None:
    """Test literal del roadmap: ``--flat`` genera solo el ``.md``."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "flat"
    result = _runner_convert(
        [str(pdf), "--out", str(out_dir), "--chapter", "3", "--flat"]
    )

    assert result.exit_code == 0, (result.stdout, result.stderr)

    expected_md = out_dir / "rust-handbook.md"
    assert expected_md.is_file()
    assert expected_md.stat().st_size > 0

    # No debe existir la carpeta del libro, ni images/, ni capmd.json.
    assert not (out_dir / "rust-handbook").exists()
    listed = list(out_dir.iterdir())
    assert listed == [expected_md]


def test_flat_skips_image_extraction(tmp_path: Path) -> None:
    """``--flat`` no extrae imágenes aunque el PDF tenga contenido gráfico."""
    pdf = build.build_headings_pdf(tmp_path / "Rust Handbook.pdf")
    out_dir = tmp_path / "flatimg"
    result = _runner_convert([str(pdf), "--out", str(out_dir), "--flat"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert (out_dir / "rust-handbook.md").is_file()
    # Sin subcarpeta del libro, sin images/, sin capmd.json.
    listed = list(out_dir.iterdir())
    assert listed == [out_dir / "rust-handbook.md"]


# --- Mutually exclusive validation ----------------------------------------


def test_out_and_output_together_error(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    result = _runner_convert(
        [str(pdf), "-o", str(tmp_path / "a.md"), "--out", str(tmp_path / "b")]
    )
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "mutuamente excluyentes" in combined or "BadParameter" in combined


def test_flat_without_out_errors(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    result = _runner_convert([str(pdf), "--flat"])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "--flat" in combined or "BadParameter" in combined


# --- Regression: existing -o FILE behavior is intact ----------------------


def test_minus_o_file_still_works(tmp_path: Path) -> None:
    """F1 NO rompe el flujo ``-o FILE``: produce un único archivo, sin árbol."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "single.md"
    result = _runner_convert([str(pdf), "-o", str(out)])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert out.is_file()
    # F1 no agregó una subcarpeta de árbol al usar ``-o``: el output es
    # exactamente el mismo path que tenía pre-F1.
    assert not (tmp_path / "rust-handbook").exists()


# --- Collision ------------------------------------------------------------


def test_out_over_existing_dir_errors(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "collide"
    (out_dir / "rust-handbook" / "cap-03-ownership").mkdir(parents=True)

    result = _runner_convert([str(pdf), "--out", str(out_dir), "--chapter", "3"])

    assert result.exit_code == 7  # IOError exit code (definido en A3)
    combined = (result.stdout or "") + (result.stderr or "")
    assert "ya existe" in combined


# --- Stdin + --out ---------------------------------------------------------


def test_out_with_stdin_uses_stdin_slug_and_null_source(tmp_path: Path) -> None:
    """Stdin + ``--out`` funciona: book_slug='stdin', source_file=None."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "stdin-tree"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", "-", "--ext", "pdf", "--out", str(out_dir)],
        input=pdf.read_bytes(),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    chap_dir = out_dir / "stdin" / "full"
    assert chap_dir.is_dir()
    payload = json.loads((chap_dir / "capmd.json").read_text(encoding="utf-8"))
    assert payload["book_slug"] == "stdin"
    assert payload["source_file"] is None
    assert payload["source_sha256"] is None
    assert payload["pages"] is None
    assert payload["range_label"] == "full"


# --- Help text ------------------------------------------------------------


def test_help_mentions_out_and_flat() -> None:
    result = CliRunner().invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--out" in result.stdout
    assert "--flat" in result.stdout
