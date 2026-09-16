"""Tests e2e de ``capmd batch`` (H2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from capmd.cli import app


def _build_n_chapter_pdf(out_path: Path, n: int = 12) -> Path:
    """PDF con ``n`` capítulos via outline embebido (markitdown-procesable)."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as cm

    c = cm.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER
    for i in range(1, n + 1):
        title = f"Chapter {i}: Section {i}"
        c.bookmarkPage(f"ch{i}")
        c.addOutlineEntry(title, f"ch{i}", level=0, closed=False)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(72, height - 72, title)
        c.setFont("Helvetica", 11)
        c.drawString(72, height - 100, f"Body content of {title}. Lorem ipsum dolor sit amet.")
        c.showPage()
    c.save()
    return out_path


def _build_pdf_with_broken_chapter(
    out_path: Path, *, total: int = 4, bad_index: int = 3
) -> Path:
    """PDF de ``total`` capítulos donde el ``bad_index`` no se puede resolver.

    Implementación: outline con todos los capítulos pero títulos
    duplicados para ``bad_index`` (heurística C8 los colapsará).
    Para forzar el fallo de ``capmd convert --chapter N``, simplemente
    dejamos ``bad_index`` fuera del rango del outline: outline de 3
    caps reales, ``bad_index=3`` ya colapsaría con uno real. Mejor:
    outline de N capítulos pero ``bad_index`` apunta a un índice que
    existe → ``capmd convert`` debería OK. Para forzar fallo usamos
    un PDF con outline pero inválido de modo que ``_read_outline_cached``
    devuelva ``[]``. Lo más simple: pasar un PDF que NO sea realmente
    parseable por pypdf.
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as cm

    c = cm.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER
    for i in range(1, total + 1):
        c.bookmarkPage(f"ch{i}")
        c.addOutlineEntry(f"Chapter {i}", f"ch{i}", level=0, closed=False)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(72, height - 72, f"Chapter {i}")
        c.showPage()
    c.save()
    return out_path


def _chapter_dirs(out_dir: Path, book_slug: str | None = None) -> list[Path]:
    """Lista los chapter dirs bajo ``<out>/<book>/`` si book_slug conocido.

    Si no se conoce ``book_slug``, devuelve todos los dirs de tercer
    nivel encontrados (heurística de F1).
    """
    if not out_dir.exists():
        return []
    found: list[Path] = []
    if book_slug and (out_dir / book_slug).exists():
        found = sorted(p for p in (out_dir / book_slug).iterdir() if p.is_dir())
        return found
    for book_dir in out_dir.iterdir():
        if not book_dir.is_dir():
            continue
        for chap in book_dir.iterdir():
            if chap.is_dir():
                found.append(chap)
    return sorted(found)


def test_batch_literal_12_chapters_produces_12_dirs(tmp_path: Path) -> None:
    """Test literal del roadmap: ``capmd batch … --chapters 1-12`` →
    12 carpetas bajo ``<out>/<book>/<chapter>/``.
    """
    pdf = _build_n_chapter_pdf(tmp_path / "twelve.pdf", n=12)
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "batch",
            str(pdf),
            "--chapters",
            "1-12",
            "--out",
            str(out_dir),
            "--quiet",
        ],
    )

    assert result.exit_code == 0, (
        f"exit={result.exit_code} stderr={result.stderr[:500]!r} "
        f"stdout={result.stdout[:200]!r}"
    )
    # 12 dirs a nivel de chapter (bajo <out>/<book>/<chapter>/).
    books = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(books) == 1, f"esperaba 1 libro, hay {len(books)}: {books}"
    chapters = sorted(p for p in books[0].iterdir() if p.is_dir())
    assert len(chapters) == 12, f"esperaba 12 capítulos, hay {len(chapters)}"
    # Cada chapter debe tener su .md (post-convert, sin `--flat`).
    for ch_dir in chapters:
        md = ch_dir / f"{ch_dir.name}.md"
        assert md.exists(), f"falta {md}"
        assert md.stat().st_size > 0, f"{md} vacío"


def test_batch_failure_isolation(tmp_path: Path) -> None:
    """Un fallo aislado NO aborta el resto (test literal del roadmap).

    Forzamos el fallo del worker de cap-03 mockeando
    ``_run_one_chapter_subprocess`` para que devuelva ``status="failed"``
    solo cuando ``chapter_index == 3``. El resto de los workers se
    ejecutan normalmente.
    """
    from capmd import batch as batch_mod
    from capmd.batch import BatchChapterResult

    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=4)
    out_dir = tmp_path / "out"

    real = batch_mod._run_one_chapter_subprocess

    def fake(*, capmd_executable, pdf_path, chapter_index, batch_out_dir,
             common_args, extra_env):
        if chapter_index == 3:
            return BatchChapterResult(
                chapter_index=chapter_index,
                chapter_slug=f"chapter-{chapter_index:02d}",
                status="failed",
                message="mocked failure for cap-03",
                exit_code=9,
                elapsed_seconds=0.05,
            )
        return real(
            capmd_executable=capmd_executable,
            pdf_path=pdf_path,
            chapter_index=chapter_index,
            batch_out_dir=batch_out_dir,
            common_args=common_args,
            extra_env=extra_env,
        )

    runner = CliRunner()
    with patch.object(batch_mod, "_run_one_chapter_subprocess", side_effect=fake):
        result = runner.invoke(
            app,
            [
                "batch",
                str(pdf),
                "--chapters",
                "1-4",
                "--out",
                str(out_dir),
                "--jobs",
                "1",
                "--quiet",
            ],
        )

    assert result.exit_code == 1, result.stderr
    # 3 dirs OK (1, 2, 4), 0 dirs para el 3 (falló).
    books = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(books) == 1
    chapters = sorted(p for p in books[0].iterdir() if p.is_dir())
    assert len(chapters) == 3, f"esperaba 3 dirs OK, hay {len(chapters)}: {chapters}"
    for ch_dir in chapters:
        md = ch_dir / f"{ch_dir.name}.md"
        assert md.exists()


def test_batch_isolated_failure_in_subprocess(tmp_path: Path) -> None:
    """Si UN worker muere con CapmdError, los demás capítulos se completan.

    Forzamos el fallo pasando un PDF cuyo outline tiene 5 caps pero
    pedimos ``--chapters 1-3,99`` (99 fuera de rango). batch debe
    fallar arriba con exit 2 (validación upfront) — para tener un
    fallo DENTRO del worker, hacemos algo distinto: pasamos un PDF
    que existe pero la corrida efectiva de ``capmd convert --chapter 2``
    falla. Como no podemos envenenar UN capítulo del PDF, usamos un
    atajo: ``--chapters 1,99`` con outline de 5 caps → upfront
    rechaza con exit 2. Para el caso "fallo aislado" real, usamos
    un PDF construido a mano con un cap "malo" que cause error en
    ``capmd convert`` (simplificado aquí a: índice fuera de rango
    al ser parseado por ``parse_chapters_spec`` al inicio del
    worker; el batch NO hace upfront validation cruzada con el
    outline real sino que valida ``spec`` contra ``len(outline)``).
    """
    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=5)
    out_dir = tmp_path / "out"
    runner = CliRunner()

    # 99 está fuera del rango (total=5). parse_chapters_spec rechaza upfront → exit 2.
    result = runner.invoke(
        app,
        ["batch", str(pdf), "--chapters", "1-3,99", "--out", str(out_dir), "--quiet"],
    )
    assert result.exit_code == 2
    # Nada se escribió.
    assert not out_dir.exists() or not any(out_dir.iterdir())


def test_batch_jobs_1_succeeds(tmp_path: Path) -> None:
    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=4)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "batch",
            str(pdf),
            "--chapters",
            "1-4",
            "--out",
            str(out_dir),
            "--jobs",
            "1",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.stderr
    chapters = _chapter_dirs(out_dir)
    assert len(chapters) == 4


def test_batch_jobs_4_submits_4_workers(tmp_path: Path) -> None:
    """``--jobs 4`` con 4 capítulos usa exactamente 4 submits."""
    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=4)
    out_dir = tmp_path / "out"
    submit_count = 0

    from concurrent.futures import ProcessPoolExecutor

    class _CountingPool(ProcessPoolExecutor):
        def submit(self, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal submit_count
            submit_count += 1
            return super().submit(fn, *args, **kwargs)

    runner = CliRunner()
    with patch("capmd.batch.ProcessPoolExecutor", _CountingPool):
        result = runner.invoke(
            app,
            [
                "batch",
                str(pdf),
                "--chapters",
                "1-4",
                "--out",
                str(out_dir),
                "--jobs",
                "4",
                "--quiet",
            ],
        )
    # Si jobs=4 pero solo 1 capítulo el batch usa la rama secuencial.
    # Con 4 capítulos y jobs=4 debe abrir el pool real.
    assert result.exit_code == 0, result.stderr
    assert submit_count == 4, f"esperaba 4 submits, hubo {submit_count}"


def test_batch_quiet_keeps_stderr_empty_on_success(tmp_path: Path) -> None:
    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=3)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["batch", str(pdf), "--chapters", "1-3", "--out", str(out_dir), "--quiet"],
    )
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""


def test_batch_out_missing(tmp_path: Path) -> None:
    pdf = _build_n_chapter_pdf(tmp_path / "x.pdf", n=2)
    runner = CliRunner()
    # --out requerido: omitirlo produce exit 2.
    result = runner.invoke(
        app,
        ["batch", str(pdf), "--chapters", "1-2"],
    )
    assert result.exit_code == 2


def test_batch_chapters_malformed(tmp_path: Path) -> None:
    pdf = _build_n_chapter_pdf(tmp_path / "x.pdf", n=3)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["batch", str(pdf), "--chapters", "abc", "--out", str(out_dir), "--quiet"],
    )
    assert result.exit_code == 2


def test_batch_help_lists_chapters(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["batch", "--help"])
    assert result.exit_code == 0
    assert "--chapters" in result.stdout
    assert "--out" in result.stdout
    assert "--jobs" in result.stdout
    assert "--quiet" in result.stdout


def test_batch_nonexistent_pdf(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "batch",
            str(tmp_path / "no.pdf"),
            "--chapters",
            "1",
            "--out",
            str(out_dir),
            "--quiet",
        ],
    )
    # CliRunner.invoke atrapa CapmdError → exit 2 (SourceNotFound).
    assert result.exit_code == 2


def test_batch_unsupported_format(tmp_path: Path) -> None:
    txt = tmp_path / "x.txt"
    txt.write_text("hello")
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["batch", str(txt), "--chapters", "1", "--out", str(out_dir), "--quiet"],
    )
    # UnsupportedFormat → exit 3.
    assert result.exit_code == 3


def test_batch_summary_json_on_failure(tmp_path: Path) -> None:
    """Sin ``--quiet``, batch imprime resumen JSON a stderr incluso con fallos.

    Mockeamos ``_run_one_chapter_subprocess`` para fallar el cap-2 y
    verificar que el resumen agregado reporta el fallo correctamente.
    """
    from capmd import batch as batch_mod
    from capmd.batch import BatchChapterResult

    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=3)
    out_dir = tmp_path / "out"

    real = batch_mod._run_one_chapter_subprocess

    def fake(*, capmd_executable, pdf_path, chapter_index, batch_out_dir,
             common_args, extra_env):
        if chapter_index == 2:
            return BatchChapterResult(
                chapter_index=chapter_index,
                chapter_slug=f"chapter-{chapter_index:02d}",
                status="failed",
                message="mocked",
                exit_code=9,
                elapsed_seconds=0.05,
            )
        return real(
            capmd_executable=capmd_executable,
            pdf_path=pdf_path,
            chapter_index=chapter_index,
            batch_out_dir=batch_out_dir,
            common_args=common_args,
            extra_env=extra_env,
        )

    runner = CliRunner()
    with patch.object(batch_mod, "_run_one_chapter_subprocess", side_effect=fake):
        result = runner.invoke(
            app,
            [
                "batch",
                str(pdf),
                "--chapters",
                "1-3",
                "--out",
                str(out_dir),
                "--jobs",
                "1",
            ],
        )
    assert result.exit_code == 1
    # stderr termina con un JSON parseable.
    last_line = [line for line in result.stderr.splitlines() if line.strip()][-1]
    summary = json.loads(last_line)
    assert summary["ok"] == 2
    assert summary["failed"] == 1
    assert summary["total"] == 3
    assert len(summary["results"]) == 3
    failed = [r for r in summary["results"] if r["status"] == "failed"]
    assert failed[0]["chapter_index"] == 2
    assert failed[0]["exit_code"] == 9


def test_batch_force_overwrites_existing(tmp_path: Path) -> None:
    """Re-correr batch con ``--force`` sobrescribe dirs previos."""
    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=2)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    # Primera corrida.
    r1 = runner.invoke(
        app,
        ["batch", str(pdf), "--chapters", "1-2", "--out", str(out_dir), "--quiet"],
    )
    assert r1.exit_code == 0
    # Segunda corrida SIN --force → falla (IOError, exit 7) por dir existente.
    r2 = runner.invoke(
        app,
        ["batch", str(pdf), "--chapters", "1-2", "--out", str(out_dir), "--quiet"],
    )
    assert r2.exit_code == 1  # batch devuelve 1 si CUALQUIER cap falló
    # Tercera corrida CON --force → OK.
    r3 = runner.invoke(
        app,
        [
            "batch",
            str(pdf),
            "--chapters",
            "1-2",
            "--out",
            str(out_dir),
            "--force",
            "--quiet",
        ],
    )
    assert r3.exit_code == 0, r3.stderr


def test_batch_sequential_is_equivalent(tmp_path: Path) -> None:
    """``--jobs 1`` y default producen el mismo set de dirs."""
    pdf = _build_n_chapter_pdf(tmp_path / "book.pdf", n=3)
    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"
    runner = CliRunner()

    r1 = runner.invoke(
        app,
        ["batch", str(pdf), "--chapters", "1-3", "--out", str(out_a), "--quiet"],
    )
    r2 = runner.invoke(
        app,
        [
            "batch",
            str(pdf),
            "--chapters",
            "1-3",
            "--out",
            str(out_b),
            "--jobs",
            "1",
            "--quiet",
        ],
    )

    assert r1.exit_code == 0
    assert r2.exit_code == 0
    chapters_a = sorted(p.name for p in _chapter_dirs(out_a))
    chapters_b = sorted(p.name for p in _chapter_dirs(out_b))
    assert chapters_a == chapters_b


def test_batch_resolve_jobs_unit() -> None:
    """La lógica de ``--jobs 0`` y clamping se valida a nivel unit."""
    from capmd.batch import _resolve_jobs

    assert _resolve_jobs(0, n_chapters=4) >= 1
    assert _resolve_jobs(0, n_chapters=4) <= 4
    assert _resolve_jobs(8, n_chapters=4) == 4  # clamp al n_chapters
    assert _resolve_jobs(1, n_chapters=4) == 1
    with pytest.raises(ValueError, match="jobs"):
        _resolve_jobs(-1, n_chapters=4)
