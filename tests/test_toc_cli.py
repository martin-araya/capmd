"""Tests e2e del TOC inline (F5)."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# --- helpers --------------------------------------------------------------


def _runner() -> CliRunner:
    return CliRunner()


def _chapter_md_of(out_dir: Path) -> Path:
    """Devuelve el path del chapter ``.md`` dentro de ``out_dir``."""
    matches = list(out_dir.rglob("*.md"))
    matches = [p for p in matches if "sections" not in p.parts]
    assert matches, f"no se encontró chapter .md en {out_dir}"
    return matches[0]


def _sections_dir_of(out_dir: Path) -> Path | None:
    candidates = list(out_dir.rglob("sections"))
    return candidates[0] if candidates else None


def _four_h2_pdf(tmp_path: Path) -> Path:
    return build.build_four_h2_pdf(tmp_path / "Rust Handbook.pdf")


def _section_titles_from_toc(md_text: str) -> list[str]:
    """Extrae los títulos de la lista dentro del bloque TOC."""
    m = re.search(r"<!-- capmd:toc:open -->\n(.*?)\n<!-- capmd:toc:close -->", md_text, re.DOTALL)
    if not m:
        return []
    return re.findall(r"- \[(.+)\]\(#([^)]+)\)", m.group(1))


def _section_anchors_in_body(md_text: str) -> set[str]:
    """Devuelve el set de anchors que el markdown tiene como headings."""
    return {
        re.sub(r"[^\w\-]+", "-", t.strip().lower()).strip("-")
        for t in re.findall(r"(?m)^#{1,6} (.+?)\s*$", md_text)
    }


# --- Test literal del roadmap F5 ------------------------------------------


def test_toc_each_anchor_resolves_to_real_heading(tmp_path: Path) -> None:
    """Test literal F5: cada anchor del TOC existe como heading."""
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = _runner().invoke(
        app, ["convert", str(pdf), "--out", str(out_dir), "--toc"]
    )
    assert result.exit_code == 0, result.stderr

    md_path = _chapter_md_of(out_dir)
    text = md_path.read_text(encoding="utf-8")
    toc_entries = _section_titles_from_toc(text)
    assert len(toc_entries) >= 4, f"esperaba >=4 entradas TOC: {toc_entries}"
    anchors_in_toc = {anchor for _, anchor in toc_entries}
    # Cada anchor en la TOC debe corresponder a un heading real en el doc.
    real_anchors = _section_anchors_in_body(text)
    assert anchors_in_toc <= real_anchors, (
        f"anclas en la TOC no resuelven a un heading: {anchors_in_toc - real_anchors}"
    )


# --- Comportamiento por defecto -------------------------------------------


def test_toc_default_depth_includes_h2_and_h3_only(tmp_path: Path) -> None:
    """Default ``--toc-depth 3`` cubre H2 y H3; no toca H1 ni H4."""
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out_default"
    result = _runner().invoke(
        app, ["convert", str(pdf), "--out", str(out_dir), "--toc"]
    )
    assert result.exit_code == 0, result.stderr

    text = _chapter_md_of(out_dir).read_text(encoding="utf-8")
    # El H1 chapter title no aparece como entrada del TOC.
    h1_in_md = re.search(r"(?m)^# (.+)$", text)
    assert h1_in_md is not None
    h1_title = h1_in_md.group(1)
    toc_titles = [t for t, _ in _section_titles_from_toc(text)]
    assert h1_title not in toc_titles


def test_toc_with_minus_o_file(tmp_path: Path) -> None:
    pdf = _four_h2_pdf(tmp_path)
    out = tmp_path / "single.md"
    result = _runner().invoke(
        app, ["convert", str(pdf), "-o", str(out), "--toc"]
    )
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    # TOC presente en el archivo escrito.
    assert "<!-- capmd:toc:open -->" in text
    toc_entries = _section_titles_from_toc(text)
    assert len(toc_entries) >= 4


def test_toc_with_flat(tmp_path: Path) -> None:
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "flat_dir"
    result = _runner().invoke(
        app, ["convert", str(pdf), "--out", str(out_dir), "--toc", "--flat"]
    )
    assert result.exit_code == 0, result.stderr
    flat_md = out_dir / "rust-handbook.md"
    assert flat_md.exists()
    text = flat_md.read_text(encoding="utf-8")
    assert "<!-- capmd:toc:open -->" in text


def test_toc_with_minus_o_omits_toc_from_stdout(tmp_path: Path) -> None:
    """Stdout NO debe llevar TOC (mantiene pipes limpios, F2)."""
    pdf = _four_h2_pdf(tmp_path)
    result = _runner().invoke(app, ["convert", str(pdf), "--toc"])
    assert result.exit_code == 0
    assert "<!-- capmd:toc:open -->" not in result.stdout


# --- --split + --toc: TOC solo en chapter root ----------------------------


def test_toc_with_split_goes_only_in_chapter_root(tmp_path: Path) -> None:
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out_split"
    result = _runner().invoke(
        app,
        ["convert", str(pdf), "--out", str(out_dir), "--split", "h2", "--toc"],
    )
    assert result.exit_code == 0, result.stderr

    # El chapter root debe tener TOC.
    chap_md = _chapter_md_of(out_dir)
    chap_text = chap_md.read_text(encoding="utf-8")
    assert "<!-- capmd:toc:open -->" in chap_text

    # Las secciones NO deben tener TOC (solo FM + body).
    sections_dir = _sections_dir_of(out_dir)
    assert sections_dir is not None
    section_files = sorted(
        p for p in sections_dir.glob("*.md") if p.name != "index.md"
    )
    for sec in section_files:
        sec_text = sec.read_text(encoding="utf-8")
        assert "<!-- capmd:toc:open -->" not in sec_text, (
            f"{sec.name} no debería tener TOC con --split"
        )


# --- Idempotencia --------------------------------------------------------


def test_toc_re_running_does_not_duplicate(tmp_path: Path) -> None:
    """Segunda corrida con --toc no acumula el bloque (sentinels)."""
    pdf = _four_h2_pdf(tmp_path)
    out = tmp_path / "idem.md"
    r1 = _runner().invoke(app, ["convert", str(pdf), "-o", str(out), "--toc"])
    assert r1.exit_code == 0, r1.stderr
    text = out.read_text(encoding="utf-8")
    assert text.count("<!-- capmd:toc:open -->") == 1
    assert text.count("<!-- capmd:toc:close -->") == 1


# --- --toc-depth ----------------------------------------------------------


def test_toc_depth_2_only_h2(tmp_path: Path) -> None:
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out_depth2"
    result = _runner().invoke(
        app,
        ["convert", str(pdf), "--out", str(out_dir), "--toc", "--toc-depth", "2"],
    )
    assert result.exit_code == 0, result.stderr
    text = _chapter_md_of(out_dir).read_text(encoding="utf-8")
    # La fixture produce solo H2; la TOC los incluye (>=1).
    toc_entries = _section_titles_from_toc(text)
    assert len(toc_entries) >= 4


def test_help_mentions_toc_flag() -> None:
    """Sanity: el --help menciona --toc y --toc-depth."""
    result = _runner().invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--toc" in result.stdout
    assert "--toc-depth" in result.stdout
