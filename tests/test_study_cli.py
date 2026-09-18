"""Tests end-to-end del perfil ``study`` (K2) via CLI."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "Rust Handbook.pdf")


def _headings_pdf(tmp_path: Path) -> Path:
    return build.build_headings_pdf(tmp_path / "headings.pdf")


def _runner_convert(args: list[str]) -> object:
    return CliRunner().invoke(app, ["convert", *args])


def _extract_yaml_block(text: str) -> dict:
    assert text.startswith("---\n"), "el texto no arranca con YAML"
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert m is not None, "no se encontró el cierre ---"
    return yaml.safe_load(m.group(1))


# ---------------------------------------------------------------------------
# --profile study: body mutations
# ---------------------------------------------------------------------------


def test_cli_profile_study_appends_three_empty_sections(tmp_path: Path) -> None:
    """``--profile study`` appendea ``## Resumen`` / ``## Conceptos clave`` / ``## Dudas`` al cuerpo."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert([str(pdf), "--profile", "study", "-o", str(out), "--chapter", "3"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    text = out.read_text(encoding="utf-8")
    # Las secciones van al final del body (después del FM).
    body = text.split("---\n\n", 1)[1]
    assert body.rstrip().endswith("## Resumen\n\n## Conceptos clave\n\n## Dudas")
    # Y NO están en el medio (deben ir al final del cuerpo).
    assert "## Resumen" in body
    assert body.count("## Resumen") == 1


def test_cli_without_profile_study_does_not_append_sections(tmp_path: Path) -> None:
    """Sin ``--profile study``, las secciones NO se appendean (la feature es opt-in)."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--chapter", "3"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    text = out.read_text(encoding="utf-8")
    assert "## Resumen" not in text
    assert "## Conceptos clave" not in text
    assert "## Dudas" not in text


def test_cli_profile_unknown_value_exits_nonzero(tmp_path: Path) -> None:
    """``--profile invalid`` falla con ``typer.BadParameter``."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert([str(pdf), "--profile", "bogus", "-o", str(out)])
    assert result.exit_code != 0
    assert "no soportado" in result.stderr


def test_cli_reading_status_invalid_exits_nonzero(tmp_path: Path) -> None:
    """``--reading-status done`` falla con BadParameter."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert(
        [str(pdf), "--profile", "study", "--reading-status", "done", "-o", str(out)]
    )
    assert result.exit_code != 0
    assert "reading_status" in result.stderr.lower() or "inv" in result.stderr.lower()


# ---------------------------------------------------------------------------
# --profile study: front matter sub-block
# ---------------------------------------------------------------------------


def test_cli_profile_study_front_matter_has_study_subkey(tmp_path: Path) -> None:
    """El FM del output tiene sub-key ``study:`` con los 4 campos."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--tag", "rust",
            "--tag", "ownership",
            "--reading-status", "in_progress",
            "-o", str(out),
            "--chapter", "3",
        ]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    fm = _extract_yaml_block(out.read_text(encoding="utf-8"))
    assert "study" in fm
    assert fm["study"]["tags"] == ["rust", "ownership"]
    assert fm["study"]["reading_status"] == "in_progress"
    # started_at se setea automáticamente por el CLI status.
    assert fm["study"]["started_at"] is not None
    assert fm["study"]["finished_at"] is None


def test_cli_without_profile_study_no_study_block_in_fm(tmp_path: Path) -> None:
    """Sin ``--profile study``, el FM no tiene la sub-key ``study:`` (compat con FMs pre-K2)."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert([str(pdf), "-o", str(out), "--chapter", "3"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    fm = _extract_yaml_block(out.read_text(encoding="utf-8"))
    assert "study" not in fm


def test_cli_tag_repeatable_accumulates_preserving_order(tmp_path: Path) -> None:
    """``--tag`` repetido acumula en orden; duplicados se deduplican."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--tag", "rust",
            "--tag", "ownership",
            "--tag", "rust",  # duplicado, debe deduplicarse
            "-o", str(out),
            "--chapter", "3",
        ]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    fm = _extract_yaml_block(out.read_text(encoding="utf-8"))
    assert fm["study"]["tags"] == ["rust", "ownership"]


def test_cli_reading_status_read_sets_finished_at(tmp_path: Path) -> None:
    """``--reading-status read`` setea ``finished_at`` (started_at queda null)."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--reading-status", "read",
            "-o", str(out),
            "--chapter", "3",
        ]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    fm = _extract_yaml_block(out.read_text(encoding="utf-8"))
    assert fm["study"]["reading_status"] == "read"
    assert fm["study"]["finished_at"] is not None
    assert fm["study"]["started_at"] is None


def test_cli_reset_study_clears_timestamps(tmp_path: Path) -> None:
    """``--reset-study`` fuerza ``started_at`` y ``finished_at`` a ``null``."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    result = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--reading-status", "read",
            "--reset-study",
            "-o", str(out),
            "--chapter", "3",
        ]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    fm = _extract_yaml_block(out.read_text(encoding="utf-8"))
    assert fm["study"]["started_at"] is None
    assert fm["study"]["finished_at"] is None


# ---------------------------------------------------------------------------
# capmd.json integration
# ---------------------------------------------------------------------------


def test_cli_profile_study_writes_capmd_json_with_study_fields(tmp_path: Path) -> None:
    """Con ``--out``, ``capmd.json`` incluye los 4 campos study no-neutrales."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "estudio"
    result = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--tag", "rust",
            "--reading-status", "in_progress",
            "--out", str(out_dir),
            "--chapter", "3",
        ]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    chapter_md = next(out_dir.rglob("*.md"))
    capmd_json = chapter_md.parent / "capmd.json"
    assert capmd_json.is_file(), f"no se creó {capmd_json}"
    data = json.loads(capmd_json.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["study_tags"] == ["rust"]
    assert data["reading_status"] == "in_progress"
    assert data["started_at"] is not None
    assert data["finished_at"] is None


def test_cli_without_profile_study_capmd_json_has_no_study_fields(tmp_path: Path) -> None:
    """Sin ``--profile study``, ``capmd.json`` no incluye los 4 campos."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "estudio"
    result = _runner_convert(
        [str(pdf), "--out", str(out_dir), "--chapter", "3"]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    capmd_json = next(out_dir.rglob("capmd.json"))
    data = json.loads(capmd_json.read_text(encoding="utf-8"))
    assert "study_tags" not in data
    assert "reading_status" not in data


# ---------------------------------------------------------------------------
# Preservation on re-conversion
# ---------------------------------------------------------------------------


def test_cli_profile_study_preserves_started_at_on_reconvert(tmp_path: Path) -> None:
    """Edit manual del ``started_at`` se preserva en re-corrida sin ``--reading-status``."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "estudio"
    chapter_md_target = out_dir / "rust-handbook" / "cap-03-ownership" / "cap-03-ownership.md"

    # 1ª corrida: setea started_at a la hora actual.
    result1 = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--reading-status", "in_progress",
            "--out", str(out_dir),
            "--chapter", "3",
        ]
    )
    assert result1.exit_code == 0
    fm1 = _extract_yaml_block(chapter_md_target.read_text(encoding="utf-8"))
    first_started_at = fm1["study"]["started_at"]
    assert first_started_at is not None

    # 2ª corrida: edit manual del started_at + re-run sin --reading-status.
    text = chapter_md_target.read_text(encoding="utf-8")
    # El timestamp puede estar envuelto en comillas simples (YAML lo
    # serializa así cuando parece fecha). Probamos ambos formatos.
    for needle in (
        f"started_at: {first_started_at}",
        f"started_at: '{first_started_at}'",
        f'started_at: "{first_started_at}"',
    ):
        if needle in text:
            text = text.replace(needle, "started_at: '2026-09-01T08:00:00Z'", 1)
            break
    else:
        pytest.fail(
            f"no se encontró el started_at original {first_started_at!r} "
            f"en el archivo (¿cambió el formato del FM?)"
        )
    chapter_md_target.write_text(text, encoding="utf-8")

    result2 = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--out", str(out_dir),
            "--chapter", "3",
            "--force",  # permitir overwrite del cap-03-ownership.md existente
        ]
    )
    assert result2.exit_code == 0, (result2.stdout, result2.stderr)

    fm2 = _extract_yaml_block(chapter_md_target.read_text(encoding="utf-8"))
    # El started_at editado a mano se preservó.
    started = fm2["study"]["started_at"]
    if hasattr(started, "strftime"):
        started = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert started == "2026-09-01T08:00:00Z"


# ---------------------------------------------------------------------------
# Stdout + help
# ---------------------------------------------------------------------------


def test_cli_profile_study_in_stdout_omits_sections(tmp_path: Path) -> None:
    """Sin ``-o``, stdout NO incluye study sections ni FM (mismo contrato que ``--toc``).

    K2 mantiene el contrato de pipes limpias: stdout solo emite el
    cuerpo limpio. Las secciones vacías y el sub-bloque ``study:`` del
    FM se aplican SOLO al output a archivo.
    """
    pdf = _outline_pdf(tmp_path)
    result = _runner_convert(
        [str(pdf), "--profile", "study", "--chapter", "3"]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    # stdout = body sin FM, sin secciones study.
    assert "## Resumen" not in result.stdout
    assert not result.stdout.startswith("---\n"), (
        "stdout no debe llevar FM"
    )


def test_cli_help_mentions_study_flags() -> None:
    """``capmd convert --help`` lista las flags nuevas."""
    result = _runner_convert(["--help"])
    assert result.exit_code == 0
    for flag in ("--profile", "--tag", "--reading-status", "--reset-study"):
        assert flag in result.stdout, f"--help no menciona {flag}"


# ---------------------------------------------------------------------------
# Combine with --split h2
# ---------------------------------------------------------------------------


def test_cli_profile_study_with_split_h2_appends_to_root_only(tmp_path: Path) -> None:
    """Con ``--split h2``, las secciones vacías van al root .md (no a sections/)."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "estudio"
    result = _runner_convert(
        [
            str(pdf),
            "--profile", "study",
            "--split", "h2",
            "--out", str(out_dir),
            "--chapter", "3",
        ]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    chapter_md = next(out_dir.rglob("cap-03-ownership.md"))
    sections_dir = chapter_md.parent / "sections"
    assert sections_dir.is_dir(), "--split h2 no generó sections/"

    # Root chapter.md tiene las secciones vacías.
    root_text = chapter_md.read_text(encoding="utf-8")
    assert "## Resumen" in root_text

    # Los sections files NO tienen las secciones study (las secciones de K2
    # son del capítulo completo, no de cada split).
    for section in sections_dir.glob("*.md"):
        text = section.read_text(encoding="utf-8")
        assert "## Resumen" not in text, (
            f"{section.name} no debería tener ## Resumen"
        )
