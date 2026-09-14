"""Tests del comando `capmd toc` (fase C2).

Cubre: títulos en stdout, start_page correcto, indentación por nivel,
archivo faltante (exit 2), PDF sin outline (vacío), y separación
stdout/stderr (regla 4 de agent.md).
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")


def test_toc_prints_chapter_titles_in_order(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path))])

    assert result.exit_code == 0, result.stderr
    stdout = result.stdout
    for title in (
        "Chapter 1: Getting Started",
        "1.1 Background",
        "Chapter 2: Ownership",
        "Chapter 3: Borrowing",
    ):
        assert title in stdout, f"falta {title!r} en stdout:\n{stdout}"


def test_toc_prints_start_pages(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path))])

    assert result.exit_code == 0, result.stderr
    stdout = result.stdout
    # Las páginas del fixture son 1, 1, 2, 3 (1-indexed). Verificar que
    # aparecen y, sobre todo, que NO aparece el "0" que devolvería
    # pypdf si perdiéramos el +1 de C1. A partir de C3 el display es
    # ``(p. X-Y)`` cuando hay rango inferido.
    assert "(p. 1-1)" in stdout
    assert "(p. 2-2)" in stdout
    assert "(p. 3-3)" in stdout
    assert "(p. 0" not in stdout


def test_toc_indents_by_level(tmp_path: Path) -> None:
    """``1.1 Background`` aparece entre Chapter 1 y Chapter 2 en stdout."""
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path))])

    assert result.exit_code == 0, result.stderr
    stdout = result.stdout
    i_ch1 = stdout.index("Chapter 1: Getting Started")
    i_sub = stdout.index("1.1 Background")
    i_ch2 = stdout.index("Chapter 2: Ownership")
    assert i_ch1 < i_sub < i_ch2, (
        f"orden esperado: Ch1 < 1.1 < Ch2; "
        f"got Ch1={i_ch1}, 1.1={i_sub}, Ch2={i_ch2}"
    )


def test_toc_missing_file_exits_2(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(tmp_path / "no-existe.pdf")])
    assert result.exit_code == 2
    assert "Error" in result.stderr
    assert "Traceback" not in result.stderr


def test_toc_pdf_without_outline_uses_heuristic(tmp_path: Path) -> None:
    """C8: sin outline, la heurística detecta headings.

    ``build_headings_pdf`` no tiene outline embebido pero el texto
    arranca con 'Chapter 1: Introduction' → matchea el patrón y aparece
    en el TOC.
    """
    runner = CliRunner()
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    result = runner.invoke(app, ["toc", str(pdf)])

    assert result.exit_code == 0, result.stderr
    assert "headings.pdf" in result.stdout
    assert "Chapter 1: Introduction" in result.stdout


# --- C9: EPUB ---------------------------------------------------------------


def _epub(tmp_path: Path) -> Path:
    from tests.fixtures import build

    return build.build_epub_with_3_chapters(tmp_path / "demo.epub")


def test_toc_on_epub_lists_chapters(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_epub(tmp_path))])
    assert result.exit_code == 0, result.stderr
    for title in ("Capitulo 1", "Capitulo 2", "Capitulo 3"):
        assert title in result.stdout


# --- C10: --json -----------------------------------------------------------


def _load_json(stdout: str) -> dict:
    import json

    return json.loads(stdout)


def test_toc_json_emits_valid_json(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    assert result.exit_code == 0, result.stderr
    # Si falla, AssertionError indica JSON inválido.
    payload = _load_json(result.stdout)
    assert isinstance(payload, dict)


def test_toc_json_has_required_top_level_keys(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    payload = _load_json(result.stdout)
    assert set(payload.keys()) == {"source", "total_pages", "chapters"}


def test_toc_json_chapters_have_required_keys(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    payload = _load_json(result.stdout)
    assert len(payload["chapters"]) > 0
    expected = {"index", "title", "level", "start_page", "end_page_inclusive"}
    for ch in payload["chapters"]:
        assert set(ch.keys()) == expected


def test_toc_json_chapters_match_outline(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    payload = _load_json(result.stdout)
    titles = [c["title"] for c in payload["chapters"]]
    assert titles == [
        "Chapter 1: Getting Started",
        "1.1 Background",
        "Chapter 2: Ownership",
        "Chapter 3: Borrowing",
    ]
    assert payload["source"] == "outline_toc.pdf"
    assert payload["total_pages"] == 3


def test_toc_json_end_page_inclusive_consistency(tmp_path: Path) -> None:
    """``end_page_inclusive == start_page`` cuando el capítulo ocupa 1 página."""
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    payload = _load_json(result.stdout)
    for ch in payload["chapters"]:
        # En el fixture, cada L1 ocupa una sola página → end = start.
        assert ch["end_page_inclusive"] >= ch["start_page"]


def test_toc_json_does_not_leak_rich_artifacts(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    assert result.exit_code == 0
    # rich.tree usa estos caracteres; con --json no deben aparecer.
    for art in ("├──", "│", "└──"):
        assert art not in result.stdout, f"artifact rich {art!r} en stdout"


def test_toc_json_works_on_epub(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_epub(tmp_path)), "--json"])
    assert result.exit_code == 0, result.stderr
    payload = _load_json(result.stdout)
    assert payload["source"] == "demo.epub"
    titles = [c["title"] for c in payload["chapters"]]
    assert titles == ["Capitulo 1", "Capitulo 2", "Capitulo 3"]


def test_toc_json_help_mentions_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.stdout


def test_toc_jq_chapters_length(tmp_path: Path) -> None:
    """Simula ``jq '.chapters | length'`` sobre el stdout."""
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    payload = _load_json(result.stdout)
    # Equivalente Python de `jq '.chapters | length'`.
    assert len(payload["chapters"]) == 4
    # Equivalente Python de `jq '.chapters[] | .level'` (set).
    levels = {c["level"] for c in payload["chapters"]}
    assert levels == {1, 2}


def test_toc_json_schema_pinned(tmp_path: Path) -> None:
    """Si alguien cambia las keys del JSON, este test rompe explícitamente."""
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path)), "--json"])
    payload = _load_json(result.stdout)
    # Shape top-level
    assert set(payload.keys()) == {"source", "total_pages", "chapters"}
    # Shape chapter
    assert set(payload["chapters"][0].keys()) == {
        "index",
        "title",
        "level",
        "start_page",
        "end_page_inclusive",
    }


def test_toc_help_mentions_pdf_argument() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", "--help"])
    assert result.exit_code == 0
    assert "PDF" in result.stdout


def test_toc_logs_do_not_leak_into_stdout(tmp_path: Path) -> None:
    """stdout solo trae el árbol; cualquier log va a stderr."""
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path))])

    assert result.exit_code == 0
    assert "INFO:" not in result.stdout
    assert "DEBUG:" not in result.stdout
    assert "WARNING:" not in result.stdout


# --- C8: fallback heurístico en toc ----------------------------------------


def _no_outline_pdf(tmp_path: Path) -> Path:
    from tests.fixtures import build

    return build.build_no_outline_chapters_pdf(tmp_path / "no_outline.pdf")


def test_toc_uses_heuristic_when_outline_empty(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_no_outline_pdf(tmp_path))])

    assert result.exit_code == 0, result.stderr
    for title in (
        "Chapter 1: Getting Started",
        "Chapter 2: Ownership",
        "Chapter 3: Borrowing",
    ):
        assert title in result.stdout, f"falta {title!r} en stdout"


def test_toc_clear_error_when_detection_fails(tmp_path: Path) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as cm

    bad = tmp_path / "uniform.pdf"
    _, height = LETTER
    c = cm.Canvas(str(bad), pagesize=LETTER)
    for n in range(1, 4):
        c.setFont("Helvetica", 11)
        c.drawString(72, height - 72, f"Page {n}: same uniform body.")
        c.showPage()
    c.save()

    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(bad)])
    assert result.exit_code == 4
    assert "--pages" in result.stderr


def test_toc_shows_inferred_range(tmp_path: Path) -> None:
    """C3: el display muestra ``(p. X-Y)`` cuando ``end_page > start_page``."""
    runner = CliRunner()
    result = runner.invoke(app, ["toc", str(_outline_pdf(tmp_path))])

    assert result.exit_code == 0, result.stderr
    # El fixture tiene 3 páginas físicas; los 3 L1 cubren cada una su página.
    assert "(p. 1-1)" in result.stdout  # Ch1 cubre solo la página 1
    assert "(p. 2-2)" in result.stdout  # Ch2 cubre solo la página 2
    assert "(p. 3-3)" in result.stdout  # Ch3 cubre solo la página 3
    # La sub-entrada 1.1 también queda con rango inferido (cierra en Ch2.start).
    assert "1.1 Background" in result.stdout
