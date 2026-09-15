"""Tests de los flags --no-clean / --only-clean / --skip-clean (D15)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from capmd.convert import Engine
from capmd.output.frontmatter import strip_existing_front_matter
from tests.fixtures import build


def _body(text: str) -> str:
    """Devuelve el markdown sin el bloque front matter YAML inicial (F2)."""
    return strip_existing_front_matter(text)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    return build.build_header_footer_pdf(tmp_path / "h.pdf")


def test_no_clean_byte_to_byte_same_as_keep_raw(
    runner: CliRunner, tmp_path: Path, pdf_path: Path
) -> None:
    """Caso del roadmap (D15/F2): --no-clean produce el mismo cuerpo markdown que --keep-raw.

    A partir de F2 el archivo de ``-o`` lleva un bloque YAML de front
    matter arriba; el snapshot ``.capmd/raw.md`` de ``--keep-raw`` no.
    Comparamos entonces los *cuerpos* (post-strip del front matter).
    """
    out_no_clean = tmp_path / "no_clean.md"
    out_dir = tmp_path / "raw_out"
    out_dir.mkdir()

    r1 = runner.invoke(
        app,
        ["convert", str(pdf_path), "-o", str(out_no_clean), "--no-clean"],
    )
    assert r1.exit_code == 0, r1.output

    raw_snapshot = out_dir / ".capmd" / "raw.md"
    r2 = runner.invoke(
        app,
        [
            "convert",
            str(pdf_path),
            "-o",
            str(out_dir / "final.md"),
            "--keep-raw",
        ],
    )
    assert r2.exit_code == 0, r2.output

    no_clean_body = _body(out_no_clean.read_text(encoding="utf-8"))
    raw_body = _body(raw_snapshot.read_text(encoding="utf-8"))
    assert no_clean_body == raw_body


def test_no_clean_output_unchanged_from_engine(
    runner: CliRunner, tmp_path: Path, pdf_path: Path
) -> None:
    """El cuerpo de --no-clean es el mismo que el engine produce sin cleaning.

    El archivo lleva front matter (F2) arriba; solo comparamos el cuerpo.
    """
    raw_engine = Engine().convert_path(pdf_path).markdown
    out = tmp_path / "out.md"
    r = runner.invoke(app, ["convert", str(pdf_path), "-o", str(out), "--no-clean"])
    assert r.exit_code == 0, r.output
    assert _body(out.read_text(encoding="utf-8")) == raw_engine


def test_no_clean_and_keep_raw_compatible(
    runner: CliRunner, tmp_path: Path, pdf_path: Path
) -> None:
    out = tmp_path / "out.md"
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf_path),
            "-o",
            str(out),
            "--no-clean",
            "--keep-raw",
        ],
    )
    assert r.exit_code == 0, r.output
    snap = tmp_path / ".capmd" / "raw.md"
    assert snap.exists()
    assert _body(out.read_text(encoding="utf-8")) == snap.read_text(encoding="utf-8")


def test_only_clean_runs_specified_only(runner: CliRunner, tmp_path: Path, pdf_path: Path) -> None:
    out = tmp_path / "out.md"
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf_path),
            "-o",
            str(out),
            "--only-clean",
            "whitespace",
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()


def test_only_clean_with_multiple(runner: CliRunner, tmp_path: Path, pdf_path: Path) -> None:
    out = tmp_path / "out.md"
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf_path),
            "-o",
            str(out),
            "--only-clean",
            "whitespace,hyphens",
        ],
    )
    assert r.exit_code == 0, r.output


def test_skip_clean_excludes_specified(runner: CliRunner, tmp_path: Path, pdf_path: Path) -> None:
    out = tmp_path / "out.md"
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf_path),
            "-o",
            str(out),
            "--skip-clean",
            "tables",
        ],
    )
    assert r.exit_code == 0, r.output


def test_only_and_skip_mutually_exclusive(
    runner: CliRunner, tmp_path: Path, pdf_path: Path
) -> None:
    out = tmp_path / "out.md"
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf_path),
            "-o",
            str(out),
            "--only-clean",
            "whitespace",
            "--skip-clean",
            "tables",
        ],
    )
    assert r.exit_code != 0
    assert "excluyentes" in r.output.lower() or "excluyentes" in (r.stderr or "").lower()


def test_unknown_cleaner_name_errors(runner: CliRunner, tmp_path: Path, pdf_path: Path) -> None:
    out = tmp_path / "out.md"
    r = runner.invoke(
        app,
        [
            "convert",
            str(pdf_path),
            "-o",
            str(out),
            "--only-clean",
            "bogus_name",
        ],
    )
    assert r.exit_code != 0
    combined = r.output + (r.stderr or "")
    assert "bogus_name" in combined or "cleaners desconocidos" in combined


def test_help_documents_flags(runner: CliRunner) -> None:
    r = runner.invoke(app, ["convert", "--help"])
    assert r.exit_code == 0
    assert "--no-clean" in r.output
    assert "--only-clean" in r.output
    assert "--skip-clean" in r.output
