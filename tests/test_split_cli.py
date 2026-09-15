"""Tests e2e del split por secciones (F4)."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# --- helpers --------------------------------------------------------------


def _runner_convert(args: list[str]) -> object:
    return CliRunner().invoke(app, ["convert", *args])


def _outline_pdf(tmp_path: Path) -> Path:
    """PDF con outline+contenido que el HeadingReconstructor convierte en 4 H2.

    Para el literal del roadmap (4 H2 → 4 archivos) usamos
    ``build_four_h2_pdf`` con 4 H2 explícitos en la estructura del PDF;
    la pipeline los convierte a headings Markdown reconstructibles.
    """
    return build.build_outline_toc_pdf(tmp_path / "Rust Handbook.pdf")


def _four_h2_pdf(tmp_path: Path) -> Path:
    """PDF con 4 H2 explícitos en su contenido (vía Paragraph styles)."""
    return build.build_four_h2_pdf(tmp_path / "Rust Handbook.pdf")


# --- Literal test del roadmap F4 ------------------------------------------


def test_split_h2_with_4_h2_produces_four_files_and_index(tmp_path: Path) -> None:
    """Test literal F4: ``--split h2`` con 4 H2 → 4 archivos + index.md."""
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = _runner_convert([
        str(pdf), "--out", str(out_dir), "--split", "h2",
    ])

    assert result.exit_code == 0, (result.stdout, result.stderr)

    # El tree debe tener un chapter dir; el split crea sections/ dentro.
    sections_dirs = list(out_dir.rglob("sections"))
    assert sections_dirs, f"no se creó ninguna carpeta sections/ en {out_dir}"

    sections_dir = sections_dirs[0]
    listed = sorted(p.name for p in sections_dir.iterdir())

    # El literal exige 4 H2 → 4 archivos + index.md + (preludio si había).
    section_files = [n for n in listed if n != "index.md"]
    assert len(section_files) == 4, (
        f"esperaba 4 secciones + index.md, encontré: {listed}"
    )
    assert "index.md" in listed

    # El index debe tener 4 links a las secciones.
    index_text = (sections_dir / "index.md").read_text(encoding="utf-8")
    assert index_text.startswith("---\n")  # F2: front matter
    link_pattern = re.findall(r"\]\((\d{2}-[\w-]+\.md)\)", index_text)
    assert len(link_pattern) >= 4, (
        f"esperaba >=4 links en index.md, encontré {len(link_pattern)}: {link_pattern}"
    )
    # Cada link apunta a un archivo que existe.
    for link in link_pattern:
        assert (sections_dir / link).exists(), (
            f"link roto en index.md: {link}"
        )


# --- Comportamiento general -----------------------------------------------


def test_split_h2_creates_intro_when_prelude_exists(tmp_path: Path) -> None:
    """Si el markdown tiene contenido antes del primer H2, se crea 00-intro.md.

    Usa ``build_headings_pdf`` (que sí tiene cuerpo entre el H1 y el primer H2)
    en lugar de ``build_four_h2_pdf`` (sin prelude para el literal test).
    """
    pdf = build.build_headings_pdf(tmp_path / "Rust Handbook.pdf")
    out_dir = tmp_path / "out_intro"
    result = _runner_convert([str(pdf), "--out", str(out_dir), "--split", "h2"])
    assert result.exit_code == 0, (result.stderr,)

    sections_dirs = list(out_dir.rglob("sections"))
    assert sections_dirs
    sections_dir = sections_dirs[0]
    listed = sorted(p.name for p in sections_dir.iterdir())
    # ``build_headings_pdf`` produce 1 H1 + 3 H2 con prelude "Body under H1."
    assert "00-intro.md" in listed, f"00-intro.md no creado: {listed}"


def test_split_h2_index_lists_all_sections(tmp_path: Path) -> None:
    """El index.md lista cada sección con su título como texto del link."""
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out_idx"
    result = _runner_convert([str(pdf), "--out", str(out_dir), "--split", "h2"])
    assert result.exit_code == 0, (result.stderr,)

    sections_dirs = list(out_dir.rglob("sections"))
    sections_dir = sections_dirs[0]
    index_text = (sections_dir / "index.md").read_text(encoding="utf-8")

    # Cada filename de sección aparece como link.
    for section_path in sections_dir.glob("*.md"):
        if section_path.name == "index.md":
            continue
        assert f"({section_path.name})" in index_text, (
            f"index.md no menciona {section_path.name}"
        )


# --- Incompatibilidades / validaciones -----------------------------------


def test_split_h2_without_out_errors(tmp_path: Path) -> None:
    """``--split`` con ``-o FILE`` (single file) → error."""
    pdf = _four_h2_pdf(tmp_path)
    out = tmp_path / "single.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--split", "h2"])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "--split" in combined


def test_split_h2_with_minus_o_errors(tmp_path: Path) -> None:
    pdf = _four_h2_pdf(tmp_path)
    out = tmp_path / "single.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--split", "h2"])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "--split" in combined


def test_split_h2_with_flat_errors(tmp_path: Path) -> None:
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = _runner_convert([
        str(pdf), "--out", str(out_dir), "--split", "h2", "--flat",
    ])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "--split" in combined


def test_split_h3_is_unsupported(tmp_path: Path) -> None:
    """F4 solo soporta 'h2'; otros niveles BadParameter explícito."""
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out"
    result = _runner_convert([
        str(pdf), "--out", str(out_dir), "--split", "h3",
    ])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "h3" in combined or "no soportado" in combined


def test_split_without_split_flag_does_not_create_sections(tmp_path: Path) -> None:
    """Sin ``--split``, no existe ninguna ``sections/`` (regresión F1)."""
    pdf = _four_h2_pdf(tmp_path)
    out_dir = tmp_path / "out_no_split"
    result = _runner_convert([str(pdf), "--out", str(out_dir)])
    assert result.exit_code == 0, (result.stderr,)

    sections_dirs = list(out_dir.rglob("sections"))
    assert not sections_dirs, (
        f"no se esperaba ninguna carpeta sections/ sin --split: {sections_dirs}"
    )
