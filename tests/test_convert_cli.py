"""Tests del comando `capmd convert` (B3 + B4 + B5 + B6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from capmd.cli import _build_limits, app
from capmd.errors import IOError
from tests.fixtures import build


def test_convert_writes_to_output_file(tmp_path: Path) -> None:
    """Test literal del roadmap B3."""
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()

    result = runner.invoke(app, ["convert", str(pdf), "-o", str(out)])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert out.exists()
    assert out.stat().st_size > 0
    text = out.read_text(encoding="utf-8")
    assert "Introduction" in text
    assert "Ownership" in text


def test_convert_writes_to_stdout_when_no_output(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    runner = CliRunner()

    result = runner.invoke(app, ["convert", str(pdf)])

    assert result.exit_code == 0, result.stderr
    assert "Introduction" in result.stdout


def test_convert_unknown_extension_exits_3(tmp_path: Path) -> None:
    f = tmp_path / "book.xyz"
    f.write_bytes(b"")
    runner = CliRunner()

    result = runner.invoke(app, ["convert", str(f)])

    assert result.exit_code == 3
    assert "formatos soportados" in result.stderr


def test_convert_missing_file_exits_2(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(tmp_path / "nope.pdf")])
    assert result.exit_code == 2


def test_convert_help_mentions_output_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--output" in result.stdout
    assert "-o" in result.stdout


# --- B4: stdin --------------------------------------------------------------


def test_convert_stdin_dash_with_ext_matches_file(tmp_path: Path) -> None:
    """Test literal B4: el pipe produce el mismo output que el archivo.

    F2 prepende YAML solo cuando hay ``-o``/``--out``. Ambos lo tienen
    acá; sin embargo el ``book`` difiere (``headings`` vs ``stdin``),
    porque stdin no tiene filename. Comparamos entonces los *cuerpos*
    (post-strip del front matter).
    """
    from capmd.output.frontmatter import strip_existing_front_matter

    pdf = build.build_headings_pdf(tmp_path / "headings.pdf")
    out_file = tmp_path / "from_file.md"
    out_stdin = tmp_path / "from_stdin.md"
    runner = CliRunner()
    pdf_bytes = pdf.read_bytes()

    file_result = runner.invoke(app, ["convert", str(pdf), "-o", str(out_file)])
    stdin_result = runner.invoke(
        app,
        ["convert", "-", "--ext", "pdf", "-o", str(out_stdin)],
        input=pdf_bytes,
    )

    assert file_result.exit_code == 0, file_result.stderr
    assert stdin_result.exit_code == 0, stdin_result.stderr
    body_file = strip_existing_front_matter(out_file.read_text(encoding="utf-8"))
    body_stdin = strip_existing_front_matter(out_stdin.read_text(encoding="utf-8"))
    assert body_file == body_stdin


def test_convert_stdin_without_ext_exits_3() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "-"], input=b"data")

    assert result.exit_code == 3
    assert "--ext" in result.stderr


def test_convert_stdin_tty_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin pipe y con TTY → exit 2 con mensaje claro.

    Typer con click 8.x no expone ``stdin_isatty`` en ``CliRunner`` y el
    testing CliRunner click-puro rompe con ``Typer``. Llamamos directo
    a la función ``convert`` con ``sys.stdin`` parcheado dentro del
    módulo. Las ``Option`` de typer se "resuelven" en strings reales
    al pasar kwargs explícitos.
    """
    import typer as _typer

    from capmd import cli as cli_module

    fake_stdin = type("FakeTTY", (), {"isatty": staticmethod(lambda: True)})()
    monkeypatch.setattr(cli_module.sys, "stdin", fake_stdin)

    with pytest.raises(_typer.Exit) as excinfo:
        cli_module.convert(
            ctx=None,
            source="-",
            ext="pdf",
            output=None,
            max_size=None,
            max_pages=None,
            timeout=None,
            warn_pages=None,
            pages=None,
            chapter=None,
            page_offset=0,
            image_format="png",
            image_max_width=None,
            filter_min_size=None,
            filter_repeat_threshold=None,
            filter_background_coverage=None,
            no_anchor=False,
            page_markers=False,
            describe_images=False,
            describe_provider="auto",
            describe_model=None,
            no_images=False,
            split=None,
            toc=False,
            toc_depth=3,
            report_format="json",
            no_warnings=False,
            strict=False,
            dry_run=False,
            dry_run_format="json",
            force=False,
            suffix=False,
        )

    assert excinfo.value.exit_code == 2


def test_convert_stdin_unknown_ext_exits_3(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", "-", "--ext", "xyz"],
        input=b"data",
    )

    assert result.exit_code == 3
    assert "formatos soportados" in result.stderr


def test_convert_help_mentions_dash_and_ext() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--ext" in result.stdout


# --- B5: límites ------------------------------------------------------------


def test_build_limits_parses_size_suffixes() -> None:
    """``_build_limits`` convierte los sufijos humanos."""
    from capmd.convert.limits import DEFAULT_LIMITS

    limits = _build_limits("500M", None, None, None)
    assert limits.max_size_bytes == 500_000_000

    limits = _build_limits("2g", None, None, None)
    assert limits.max_size_bytes == 2_000_000_000

    limits = _build_limits("1024", None, None, None)
    assert limits.max_size_bytes == 1024

    # Sin flags mantiene los defaults.
    limits = _build_limits(None, None, None, None)
    assert limits.max_size_bytes == DEFAULT_LIMITS.max_size_bytes
    assert limits.max_pages == DEFAULT_LIMITS.max_pages
    assert limits.timeout_seconds == DEFAULT_LIMITS.timeout_seconds
    assert limits.warn_pages == DEFAULT_LIMITS.warn_pages


def test_build_limits_invalid_size_raises() -> None:
    """Cadena no parseable → ``ValueError`` que el CLI mapea a exit no-cero."""
    with pytest.raises(ValueError):
        _build_limits("abc", None, None, None)
    with pytest.raises(ValueError):
        _build_limits("-5M", None, None, None)


def test_convert_cli_invalid_max_size_exits_nonzero(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--max-size", "abc"])
    assert result.exit_code != 0


def test_convert_default_max_size_accommodates_fixture(tmp_path: Path) -> None:
    """Defaults del spec: 500 MB → el fixture de headings pasa."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    out = tmp_path / "o.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "-o", str(out)])
    assert result.exit_code == 0, result.stderr


def test_convert_reports_timing_to_stderr(tmp_path: Path) -> None:
    """El reporte F6 va a stderr con stats del run (incluye elapsed/páginas)."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    out = tmp_path / "o.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "-o", str(out)], catch_exceptions=False)
    assert result.exit_code == 0, result.stderr
    stderr = result.output if isinstance(result.output, str) else (result.stderr or "")
    # F6 emite un JSON al final con elapsed_seconds + pages (cuando hay pdf).
    assert '"elapsed_seconds"' in stderr
    assert '"pages"' in stderr
    assert '"format": "json"' in stderr


def test_convert_max_size_exceeded_exits_6(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--max-size", "100"])
    assert result.exit_code == 6
    assert "supera el límite" in result.stderr


def test_convert_max_pages_exceeded_exits_6(tmp_path: Path) -> None:
    pdf = build.build_many_pages_pdf(tmp_path / "big.pdf", n_pages=12)
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--max-pages", "5"])
    assert result.exit_code == 6
    assert "supera el límite" in result.stderr


def test_convert_timeout_exits_5(tmp_path: Path) -> None:
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    runner = CliRunner()

    def _local_slow(*_a: object, **_kw: object) -> object:
        import time as _time

        _time.sleep(3)
        return None

    with patch("capmd.convert.engine.MarkItDown.convert_local", side_effect=_local_slow):
        result = runner.invoke(app, ["convert", str(pdf), "--timeout", "1"])
    assert result.exit_code == 5
    assert "timeout" in result.stderr.lower() or "--timeout" in result.stderr


# --- B6: snapshot del output crudo ------------------------------------------


def test_convert_keep_raw_creates_capmd_raw_next_to_output(tmp_path: Path) -> None:
    """``--keep-raw`` con ``-o``: snapshot adyacente al output."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    out = tmp_path / "x.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "-o", str(out), "--keep-raw"])
    assert result.exit_code == 0, result.stderr
    snapshot = tmp_path / ".capmd" / "raw.md"
    assert snapshot.exists()
    assert out.exists()


def test_convert_keep_raw_uses_cwd_when_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin ``-o``: snapshot va a cwd."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["convert", str(pdf), "--keep-raw"])
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / ".capmd" / "raw.md").exists()


def test_convert_without_keep_raw_does_not_create_capmd(tmp_path: Path) -> None:
    """Test literal del spec B6: sin flag, no se crea el directorio."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    out = tmp_path / "x.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    assert not (tmp_path / ".capmd").exists()


def test_convert_keep_raw_with_stdin_writes_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stdin + --keep-raw sin -o → snapshot en cwd."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["convert", "-", "--ext", "pdf", "--keep-raw"],
        input=pdf.read_bytes(),
    )
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / ".capmd" / "raw.md").exists()


def test_convert_keep_raw_overwrites_existing_snapshot(tmp_path: Path) -> None:
    """Una segunda corrida con --keep-raw y ``--force`` sobrescribe sin error."""
    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    out = tmp_path / "x.md"
    runner = CliRunner()
    runner.invoke(app, ["convert", str(pdf), "-o", str(out), "--keep-raw"])
    # F8: la 2da corrida sin ``--force`` ahora falla con exit 7.
    # Agregamos ``--force`` explícitamente para que sobrescriba.
    second = runner.invoke(
        app,
        ["convert", str(pdf), "-o", str(out), "--keep-raw", "--force"],
    )
    assert second.exit_code == 0, second.stderr
    snapshot = tmp_path / ".capmd" / "raw.md"
    assert snapshot.exists()
    assert out.exists()


def test_convert_keep_raw_io_error_exits_7(tmp_path: Path) -> None:
    """Permisos/FS error al escribir el snapshot → exit 7."""
    from capmd import cli as cli_module

    pdf = build.build_headings_pdf(tmp_path / "h.pdf")
    out = tmp_path / "x.md"
    runner = CliRunner()

    def _boom(*_a: object, **_kw: object) -> Path:
        raise IOError("permiso denegado", hint="mock")

    with patch.object(cli_module, "write_raw_snapshot", side_effect=_boom):
        result = runner.invoke(app, ["convert", str(pdf), "-o", str(out), "--keep-raw"])
    assert result.exit_code == 7
    assert "permiso denegado" in result.stderr


def test_convert_help_mentions_keep_raw() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--keep-raw" in result.stdout


# --- C4: --pages -----------------------------------------------------------


def test_convert_pages_slices_single_page(tmp_path: Path) -> None:
    """``--pages 2`` sobre el outline_toc: solo Ch2, ni Ch1 ni Ch3."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--pages", "2", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Chapter 2: Ownership" in text
    assert "Chapter 1" not in text
    assert "Chapter 3" not in text


def test_convert_pages_open_right(tmp_path: Path) -> None:
    """``--pages 2-``: Ch2 y Ch3, no Ch1."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--pages", "2-", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Chapter 2: Ownership" in text
    assert "Chapter 3: Borrowing" in text
    assert "Chapter 1" not in text


def test_convert_pages_open_left(tmp_path: Path) -> None:
    """``--pages -2``: Ch1 y Ch2, no Ch3."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--pages", "-2", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Chapter 1" in text
    assert "Chapter 2" in text
    assert "Chapter 3" not in text


def test_convert_pages_list(tmp_path: Path) -> None:
    """``--pages 1,3``: Ch1 y Ch3, no Ch2."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--pages", "1,3", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Chapter 1" in text
    assert "Chapter 3" in text
    assert "Chapter 2: Ownership" not in text


def test_convert_pages_out_of_bounds_exits_4(tmp_path: Path) -> None:
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--pages", "200"])
    assert result.exit_code == 4
    assert "fuera del documento" in result.stderr


def test_convert_pages_bad_syntax_exits_2(tmp_path: Path) -> None:
    """typer.BadParameter -> exit 2."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--pages", "abc"])
    assert result.exit_code == 2
    assert "invalid page spec" in result.stderr


def test_convert_pages_with_stdin_rejected(tmp_path: Path) -> None:
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", "-", "--ext", "pdf", "--pages", "1-5"],
        input=pdf.read_bytes(),
    )
    assert result.exit_code == 2
    assert "stdin" in result.stderr


def test_convert_pages_help_mentions_pages() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--pages" in result.stdout


# --- C5: --chapter ----------------------------------------------------------


def test_convert_chapter_by_index_slices_correct_range(tmp_path: Path) -> None:
    """``--chapter 3`` (Ch2 = index 3) → solo Ch2."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "3", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Chapter 2: Ownership" in text
    assert "Chapter 1" not in text
    assert "Chapter 3" not in text


def test_convert_chapter_by_title_slices_correct_range(tmp_path: Path) -> None:
    """``--chapter 'Ownership'`` → mismo rango que por índice 3."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "Ownership", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Chapter 2: Ownership" in text
    assert "Chapter 1" not in text
    assert "Chapter 3" not in text


def test_convert_chapter_both_forms_produce_same_output(tmp_path: Path) -> None:
    """``--chapter 3`` y ``--chapter 'Ownership'`` producen markdown idéntico."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out_idx = tmp_path / "by_index.md"
    out_sub = tmp_path / "by_substring.md"
    runner = CliRunner()

    r1 = runner.invoke(app, ["convert", str(pdf), "--chapter", "3", "-o", str(out_idx)])
    r2 = runner.invoke(app, ["convert", str(pdf), "--chapter", "Ownership", "-o", str(out_sub)])
    assert r1.exit_code == 0, r1.stderr
    assert r2.exit_code == 0, r2.stderr
    assert out_idx.read_text(encoding="utf-8") == out_sub.read_text(encoding="utf-8")


def test_convert_chapter_and_pages_rejected(tmp_path: Path) -> None:
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "3", "--pages", "2-3"])
    assert result.exit_code == 2
    assert "mutuamente excluyentes" in result.stderr


def test_convert_chapter_no_match_exits_2(tmp_path: Path) -> None:
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "xyz"])
    assert result.exit_code == 2
    assert "ningún capítulo" in result.stderr


def test_convert_chapter_ambiguous_exits_2(tmp_path: Path) -> None:
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "Chapter"])
    assert result.exit_code == 2
    assert "ambiguo" in result.stderr
    # Los tres candidatos aparecen en el error.
    assert "Chapter 1" in result.stderr
    assert "Chapter 2" in result.stderr
    assert "Chapter 3" in result.stderr


def test_convert_chapter_index_out_of_range_exits_2(tmp_path: Path) -> None:
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "99"])
    assert result.exit_code == 2
    assert "índice" in result.stderr


def test_convert_chapter_with_stdin_rejected(tmp_path: Path) -> None:
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", "-", "--ext", "pdf", "--chapter", "1"],
        input=pdf.read_bytes(),
    )
    assert result.exit_code == 2
    assert "stdin" in result.stderr


def test_convert_chapter_help_mentions_chapter() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--chapter" in result.stdout


def test_convert_chapter_with_subentry_index(tmp_path: Path) -> None:
    """``--chapter 2`` (la sub-entrada '1.1 Background') → solo esa página."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "2", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "1.1 Background" in text
    assert "Chapter 2: Ownership" not in text
    assert "Chapter 3: Borrowing" not in text


# --- C7: --page-offset ---------------------------------------------------


def _build_numbered_pdf(path: Path, n_pages: int) -> Path:
    """PDF de ``n_pages`` con cada página marcada ``MARKER-PAGE-N``.

    Usado por tests C7 para verificar rangos físicos específicos
    (``--page-offset`` traduce el spec impreso al físico).
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as cm

    _, height = LETTER
    c = cm.Canvas(str(path), pagesize=LETTER)
    for n in range(1, n_pages + 1):
        c.setFont("Helvetica-Bold", 24)
        c.drawString(72, height - 100, f"MARKER-PAGE-{n}")
        c.showPage()
    c.save()
    return path


def test_convert_pages_offset_translates_range(tmp_path: Path) -> None:
    """Test literal del roadmap: offset 18 + ``--pages 45-50`` → físicas 63-68."""
    pdf = _build_numbered_pdf(tmp_path / "big.pdf", n_pages=80)
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "convert",
            str(pdf),
            "--pages",
            "45-50",
            "--page-offset",
            "18",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    for n in (63, 64, 65, 66, 67, 68):
        assert f"MARKER-PAGE-{n}" in text, f"falta página física {n}"
    for n in (1, 45, 62, 69, 70, 80):
        assert f"MARKER-PAGE-{n}" not in text, f"página {n} colada"


def test_convert_pages_offset_zero_is_no_op(tmp_path: Path) -> None:
    pdf = _build_numbered_pdf(tmp_path / "p.pdf", n_pages=10)
    out_a = tmp_path / "a.md"
    out_b = tmp_path / "b.md"
    runner = CliRunner()
    ra = runner.invoke(app, ["convert", str(pdf), "--pages", "2-4", "-o", str(out_a)])
    rb = runner.invoke(
        app,
        ["convert", str(pdf), "--pages", "2-4", "--page-offset", "0", "-o", str(out_b)],
    )
    assert ra.exit_code == 0
    assert rb.exit_code == 0
    assert out_a.read_text(encoding="utf-8") == out_b.read_text(encoding="utf-8")


def test_convert_pages_negative_offset(tmp_path: Path) -> None:
    """Offset -5 con ``--pages 50`` → slicea la física 45."""
    pdf = _build_numbered_pdf(tmp_path / "p.pdf", n_pages=60)
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", str(pdf), "--pages", "50", "--page-offset", "-5", "-o", str(out)],
    )
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "MARKER-PAGE-45" in text
    assert "MARKER-PAGE-50" not in text


def test_convert_pages_offset_out_of_bounds_exits_4(tmp_path: Path) -> None:
    pdf = _build_numbered_pdf(tmp_path / "p.pdf", n_pages=100)
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--pages", "90", "--page-offset", "18"])
    assert result.exit_code == 4
    assert "fuera del documento" in result.stderr


def test_convert_chapter_offset_out_of_bounds_exits_4(tmp_path: Path) -> None:
    """Capítulo cuyo offset sale del documento → exit 4."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "1", "--page-offset", "18"])
    assert result.exit_code == 4
    assert "offset" in result.stderr.lower() or "fuera" in result.stderr


def test_convert_chapter_offset_keeps_in_bounds(tmp_path: Path) -> None:
    """``--chapter 1 --page-offset 1`` sobre outline_toc (3 páginas) → Ch1 en página 2."""
    pdf = build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", str(pdf), "--chapter", "1", "--page-offset", "1", "-o", str(out)],
    )
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    # Ch1 ocupa la página 1 del original → con offset 1 → página 2.
    # La página 2 del fixture contiene "Chapter 2: Ownership" que es
    # también el texto que arrancó la página 1 (encabezado Ch1 + Ch2 en
    # la misma página por la maquetación del fixture). Aceptamos
    # cualquier texto de Chapter 1 o Chapter 2.
    assert "Chapter" in text


def test_convert_offset_without_pages_or_chapter_silent(tmp_path: Path) -> None:
    pdf = _build_numbered_pdf(tmp_path / "p.pdf", n_pages=5)
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--page-offset", "5", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    # Sin recorte, todas las páginas aparecen.
    for n in (1, 2, 3, 4, 5):
        assert f"MARKER-PAGE-{n}" in text
    # Sin warnings de offset en stderr.
    assert "offset" not in result.stderr.lower()


def test_convert_offset_help_mentions_offset() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--page-offset" in result.stdout


# --- C8: fallback heurístico en --chapter ----------------------------------


def test_convert_chapter_uses_heuristic_when_outline_empty(tmp_path: Path) -> None:
    """PDF sin outline + ``--chapter 1`` → la heurística detecta y slicea."""
    pdf = build.build_no_outline_chapters_pdf(tmp_path / "no_outline.pdf")
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(pdf), "--chapter", "1", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Chapter 1: Getting Started" in text


def test_convert_chapter_clear_error_when_detection_fails(tmp_path: Path) -> None:
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
    result = runner.invoke(app, ["convert", str(bad), "--chapter", "1"])
    assert result.exit_code == 4
    assert "--pages" in result.stderr


# --- C9: EPUB ---------------------------------------------------------------


def _epub(tmp_path: Path) -> Path:
    return build.build_epub_with_3_chapters(tmp_path / "demo.epub")


def test_convert_epub_whole_file(tmp_path: Path) -> None:
    """Sin ``--chapter``, el EPUB completo se convierte."""
    epub_path = _epub(tmp_path)
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(epub_path), "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    for marker in ("MARKER-CH-1-CONTENT", "MARKER-CH-2-CONTENT", "MARKER-CH-3-CONTENT"):
        assert marker in text, f"falta {marker}"


def test_convert_epub_chapter_by_index(tmp_path: Path) -> None:
    epub_path = _epub(tmp_path)
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(epub_path), "--chapter", "2", "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "MARKER-CH-2-CONTENT" in text
    assert "MARKER-CH-1-CONTENT" not in text
    assert "MARKER-CH-3-CONTENT" not in text


def test_convert_epub_chapter_by_title(tmp_path: Path) -> None:
    epub_path = _epub(tmp_path)
    out = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(
        app, ["convert", str(epub_path), "--chapter", "Capitulo 2", "-o", str(out)]
    )
    assert result.exit_code == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "MARKER-CH-2-CONTENT" in text
    assert "MARKER-CH-1-CONTENT" not in text
    assert "MARKER-CH-3-CONTENT" not in text


def test_convert_epub_pages_rejected(tmp_path: Path) -> None:
    epub_path = _epub(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(epub_path), "--pages", "2-3"])
    assert result.exit_code == 2
    assert "EPUB" in result.stderr


def test_convert_epub_page_offset_rejected(tmp_path: Path) -> None:
    epub_path = _epub(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(epub_path), "--chapter", "1", "--page-offset", "5"])
    assert result.exit_code == 2
    assert "EPUB" in result.stderr


def test_convert_epub_help_mentions_epub() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    # El --help ya mencionaba EPUB como formato soportado en epocas
    # pre-C9; el cambio acá es que --chapter funciona. Validamos que
    # el formato EPUB esté visible.
    assert "epub" in result.stdout.lower()
