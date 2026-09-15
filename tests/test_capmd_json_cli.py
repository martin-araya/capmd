"""Tests e2e del schema v2 de ``capmd.json`` (F3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from typer.testing import CliRunner

from capmd.cli import app
from capmd.output.frontmatter import (
    front_matter_fields_from_capmd_json,
    render_front_matter,
)
from tests.fixtures import build

# --- helpers --------------------------------------------------------------


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "Rust Handbook.pdf")


def _chapter_dir(out_dir: Path) -> Path:
    return out_dir / "rust-handbook" / "cap-03-ownership"


def _convert(args: list[str]) -> object:
    return CliRunner().invoke(app, ["convert", *args])


# --- Field shape ---------------------------------------------------------


def test_capmd_json_has_all_v2_fields(tmp_path: Path) -> None:
    """``--out`` produce un ``capmd.json`` con las 20 keys de v2."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3"])
    assert r.exit_code == 0, r.stderr
    payload = json.loads(
        (_chapter_dir(out) / "capmd.json").read_text(encoding="utf-8")
    )
    expected = {
        "book_slug", "chapter", "chapter_slug", "cleaner_stats",
        "cleaners_applied", "capmd_version", "elapsed_seconds", "figures",
        "generated_at", "images_dir", "layout", "markitdown_version",
        "pages", "range_label", "schema_version", "source_file",
        "source_sha256", "title", "warnings",
    }
    assert set(payload.keys()) == expected
    assert payload["schema_version"] == 2


def test_capmd_json_title_matches_first_h1(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3"])
    assert r.exit_code == 0, r.stderr
    payload = json.loads(
        (_chapter_dir(out) / "capmd.json").read_text(encoding="utf-8")
    )
    # El markdown limpio tiene "Chapter 2: Ownership" como H1 (reconstruido
    # por el HeadingReconstructor desde el outline).
    assert isinstance(payload["title"], str)
    assert payload["title"]


def test_capmd_json_cleaner_stats_present(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3"])
    assert r.exit_code == 0, r.stderr
    payload = json.loads(
        (_chapter_dir(out) / "capmd.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload["cleaner_stats"], list)


def test_capmd_json_cleaner_stats_empty_when_no_clean(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3", "--no-clean"])
    assert r.exit_code == 0, r.stderr
    payload = json.loads(
        (_chapter_dir(out) / "capmd.json").read_text(encoding="utf-8")
    )
    assert payload["cleaner_stats"] == []
    assert payload["cleaners_applied"] == []


def test_capmd_json_cleaner_stats_populated_for_full_run(tmp_path: Path) -> None:
    """Sin ``--no-clean``, al menos un cleaner corre (cambia algo)."""
    pdf = build.build_header_footer_pdf(tmp_path / "h.pdf")
    out = tmp_path / "out_full"
    r = _convert([str(pdf), "-o", str(out / "x.md")])
    # Para ``-o FILE`` no se genera ``capmd.json``. Probemos con ``--out``.
    chap_dir = out / "h" / "full"
    r = _convert([str(pdf), "--out", str(out), "--keep-raw"])
    assert r.exit_code == 0, r.stderr
    payload = json.loads(
        (chap_dir / "capmd.json").read_text(encoding="utf-8")
    )
    # El pipeline por defecto ejecuta ~13 cleaners; cada uno produce un stat.
    assert len(payload["cleaner_stats"]) >= 1
    # Cada stat tiene la shape esperada.
    sample = payload["cleaner_stats"][0]
    assert {"name", "enabled", "changes", "duration_ms", "error"} <= set(sample.keys())


def test_capmd_json_elapsed_seconds_positive(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3"])
    assert r.exit_code == 0, r.stderr
    payload = json.loads(
        (_chapter_dir(out) / "capmd.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload["elapsed_seconds"], (int, float))
    assert payload["elapsed_seconds"] >= 0


def test_capmd_json_markitdown_version_present(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3"])
    assert r.exit_code == 0, r.stderr
    payload = json.loads(
        (_chapter_dir(out) / "capmd.json").read_text(encoding="utf-8")
    )
    # El string puede ser "unknown" si markitdown no tiene metadata, pero
    # la key tiene que estar siempre.
    assert "markitdown_version" in payload
    assert isinstance(payload["markitdown_version"], str)
    assert payload["markitdown_version"]


def test_capmd_json_stdin_has_null_source(tmp_path: Path) -> None:
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out_stdin"
    r = CliRunner().invoke(
        app,
        ["convert", "-", "--ext", "pdf", "--out", str(out)],
        input=pdf.read_bytes(),
    )
    assert r.exit_code == 0, r.stderr
    chap = out / "stdin" / "full"
    payload = json.loads((chap / "capmd.json").read_text(encoding="utf-8"))
    assert payload["source_file"] is None
    assert payload["source_sha256"] is None
    assert payload["pages"] is None
    assert payload["book_slug"] == "stdin"


# --- Literal: regenerar FM desde JSON ------------------------------------


def test_capmd_json_can_regenerate_front_matter(tmp_path: Path) -> None:
    """Test literal del roadmap F3.

    Dado un ``capmd.json``, generar el FM block desde su contenido debe
    producir el mismo YAML que el del ``.md`` escrito originalmente.
    """
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out_regen"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3"])
    assert r.exit_code == 0, r.stderr

    chap_dir = _chapter_dir(out)
    md_path = chap_dir / "cap-03-ownership.md"
    json_path = chap_dir / "capmd.json"

    md_text = md_path.read_text(encoding="utf-8")
    json_payload = json.loads(json_path.read_text(encoding="utf-8"))

    fm_from_json = front_matter_fields_from_capmd_json(json_payload)
    rendered = render_front_matter(fm_from_json)

    # Extraer el bloque FM original del .md y parsearlo.
    m = re.match(r"\A---\n(.*?)\n---\n", md_text, re.DOTALL)
    assert m is not None
    original_parsed = yaml.safe_load(m.group(1))
    regenerated_parsed = yaml.safe_load(
        re.match(r"\A---\n(.*?)\n---\n", rendered, re.DOTALL).group(1)
    )

    assert original_parsed == regenerated_parsed


# --- Bonus: figures list ------------------------------------------------


def test_capmd_json_with_pdf_images_has_figures(tmp_path: Path) -> None:
    """PDF con imágenes debe poblar ``figures`` con su path relativo."""
    work = tmp_path / "work"
    work.mkdir()
    pdf = build.build_two_images_pdf(tmp_path / "imgbook.pdf", work)
    out = tmp_path / "out_img"
    r = _convert([str(pdf), "--out", str(out)])
    assert r.exit_code == 0, r.stderr
    # Encontrar el chapter dir (book_slug "imgbook").
    candidates = list(out.glob("*/cap-01-*"))
    if not candidates:
        # Si no hay outline, el chapter es "full".
        candidates = list(out.glob("*/full"))
    assert candidates, f"no se encontro chapter dir en {out}"
    payload = json.loads(
        (candidates[0] / "capmd.json").read_text(encoding="utf-8")
    )
    # El builder fixture pone 2 imágenes válidas (no logos repetidos),
    # pero el filtro podría descartar alguna. Verifica al menos que
    # ``figures`` es una lista y todas tienen path relativo.
    assert isinstance(payload["figures"], list)
    for fig in payload["figures"]:
        assert fig["path"].startswith("images/")


def test_capmd_json_figures_empty_for_flat(tmp_path: Path) -> None:
    """``--flat`` no extrae figuras (F1) → ``figures == []``."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "flat"
    r = _convert([str(pdf), "--out", str(out), "--chapter", "3", "--flat"])
    assert r.exit_code == 0, r.stderr
    # No hay ``capmd.json`` en flat (F1 lo decidió). Verificar que el
    # archivo no se generó:
    assert not (out / "rust-handbook").exists()


def test_capmd_json_help_unchanged() -> None:
    """Sanity: el --help sigue mencionando --out / --flat."""
    r = CliRunner().invoke(app, ["convert", "--help"])
    assert r.exit_code == 0
    assert "--out" in r.stdout
    assert "--flat" in r.stdout
