"""Tests de :func:`capmd.images.anchor.anchor_figures` y del anclaje end-to-end (fase E4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from capmd.convert.page_markers import (
    insert_page_markers,
    split_by_page_markers,
)
from capmd.images import anchor_figures
from capmd.models import Figure

# LETTER page height in PDF points (8.5x11").
PAGE_HEIGHT = 792.0
PAGE_WIDTH = 612.0


_NO_BBOX = object()


def _fig(
    page: int = 1,
    y_pdf: float = 100.0,
    path: Path | None = None,
    *,
    bbox=_NO_BBOX,
) -> Figure:
    """Helper: crea un Figure mínimo.

    - Si ``bbox`` no se pasa: ``(0.0, y_pdf, 100, 100)`` (origen PDF top-left).
    - Si ``bbox=_NO_BBOX`` y ``y_pdf`` no importa: ``None`` (sin bbox).
    """
    if bbox is _NO_BBOX:
        bbox = (0.0, y_pdf, 100.0, 100.0)
    if path is None:
        path = Path(f"images/fig-{page:02d}-01.png")
    return Figure(
        chapter_index=1,
        index=1,
        path=path,
        page=page,
        bbox=bbox,
        width=100,
        height=100,
    )


def _markdown_with_markers(*pages) -> str:
    """Une varias páginas en markdown con markers ``<!-- page N -->``.

    Cada page puede ser ``str`` (una sola línea / bloque) o ``list[str]``
    (varias líneas que se unen con ``\\n``).
    """
    rendered = ["\n".join(p) if isinstance(p, list) else p for p in pages]
    return insert_page_markers(rendered)


# ---------- anchor_figures: unit tests ----------


def test_anchor_figures_inserts_image_in_middle_of_page_2() -> None:
    """Caso literal del roadmap: imagen en Y=0.5 → entre párrafos, no al final."""
    page_2_lines = [
        "Paragraph A of page 2.",
        "Paragraph B of page 2.",
        "Paragraph C of page 2.",
        "Paragraph D of page 2.",
    ]
    md = _markdown_with_markers(
        ["para page 1"],
        page_2_lines,
    )
    fig = _fig(page=2, y_pdf=PAGE_HEIGHT * 0.5)

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    # El anchor debe estar dentro del bloque de página 2 (entre A-D), no al final del doc.
    pages = split_by_page_markers(out)
    assert len(pages) == 2
    assert "fig-02-01.png" in pages[1]
    # Debe aparecer en la mitad: después de 2 (B), antes de 4 (D) — al menos no al final.
    lines_p2 = pages[1].splitlines()
    img_line_idx = next(i for i, ln in enumerate(lines_p2) if "fig-02-01.png" in ln)
    assert img_line_idx < len(lines_p2) - 1, "anchor no debe ser la última línea"
    # Páginas restantes (la 1) intactas.
    assert "para page 1" in pages[0]


def test_anchor_figures_multiple_figures_same_page_sorted_by_y() -> None:
    """2 figuras en página 2 con Y distinto → ordenadas por Y, líneas distintas."""
    page_2 = [
        "Para A.",
        "Para B.",
        "Para C.",
        "Para D.",
    ]
    md = _markdown_with_markers(["p1"], page_2)
    fig_top = _fig(
        page=2, y_pdf=100.0, path=Path("images/fig-02-01.png"), bbox=(0.0, 100.0, 100.0, 100.0)
    )
    fig_bottom = _fig(
        page=2, y_pdf=600.0, path=Path("images/fig-02-02.png"), bbox=(0.0, 600.0, 100.0, 100.0)
    )

    out = anchor_figures(
        md, [fig_bottom, fig_top], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)}
    )  # Intencionalmente desordenadas en la entrada; deben ir ordenadas por Y.

    pages = split_by_page_markers(out)
    lines_p2 = pages[1].splitlines()
    idx_top = next(i for i, ln in enumerate(lines_p2) if "fig-02-01.png" in ln)
    idx_bottom = next(i for i, ln in enumerate(lines_p2) if "fig-02-02.png" in ln)
    assert idx_top < idx_bottom


def test_anchor_figures_image_at_top_of_page() -> None:
    """Y=0 → anchor insertado en línea 0 (lo más temprano posible del bloque)."""
    md = _markdown_with_markers(
        ["page1 line A", "page1 line B"],
        ["page2 line A", "page2 line B"],
    )
    fig = _fig(page=2, y_pdf=0.0)

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    pages = split_by_page_markers(out)
    lines_p2 = pages[1].splitlines()
    idx = next(i for i, ln in enumerate(lines_p2) if "fig-02-01.png" in ln)
    assert idx == 0


def test_anchor_figures_image_at_bottom_of_page() -> None:
    """Y cerca del alto total → anchor al final del bloque."""
    md = _markdown_with_markers(
        ["p1"],
        ["p2-A", "p2-B"],
    )
    fig = _fig(page=2, y_pdf=PAGE_HEIGHT - 10.0)  # y_frac > 0.98

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    pages = split_by_page_markers(out)
    lines_p2 = pages[1].splitlines()
    idx = next(i for i, ln in enumerate(lines_p2) if "fig-02-01.png" in ln)
    assert idx == len(lines_p2) - 1


def test_anchor_figures_no_bbox_appends_to_end_of_page() -> None:
    md = _markdown_with_markers(
        ["p1-A", "p1-B"],
        ["p2-A", "p2-B"],
    )
    fig = _fig(page=2, bbox=None, path=Path("images/fig-02-01.png"))
    fig = Figure(
        chapter_index=1,
        index=1,
        path=fig.path,
        page=2,
        bbox=None,
        width=100,
        height=100,
    )

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    pages = split_by_page_markers(out)
    assert "fig-02-01.png" in pages[1]
    lines_p2 = pages[1].splitlines()
    idx = next(i for i, ln in enumerate(lines_p2) if "fig-02-01.png" in ln)
    assert idx == len(lines_p2) - 1, "sin bbox cae al final del bloque"


def test_anchor_figures_empty_figures_no_change() -> None:
    md = _markdown_with_markers(["A"], ["B"])
    out = anchor_figures(
        md, [], page_areas={1: (PAGE_WIDTH, PAGE_HEIGHT), 2: (PAGE_WIDTH, PAGE_HEIGHT)}
    )
    assert out == md


def test_anchor_figures_preserves_markers() -> None:
    md = _markdown_with_markers(
        ["page1"],
        ["A", "B"],
    )
    fig = _fig(page=2, y_pdf=PAGE_HEIGHT * 0.5)
    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    assert "<!-- page 2 -->" in out
    pages = split_by_page_markers(out)
    assert len(pages) == 2


def test_anchor_figures_does_not_split_paragraphs() -> None:
    """El anchor llega en su propia línea (no pegada a un párrafo)."""
    md = _markdown_with_markers(["p1"], ["para A", "para B", "para C", "para D"])
    fig = _fig(page=2, y_pdf=PAGE_HEIGHT * 0.5)

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    pages = split_by_page_markers(out)
    lines_p2 = pages[1].splitlines()
    idx = next(i for i, ln in enumerate(lines_p2) if "fig-02-01.png" in ln)
    # El anchor ocupa una línea entera (empieza con "!").
    assert lines_p2[idx].startswith("![")
    # La línea siguiente es blank (separación con el siguiente párrafo).
    assert lines_p2[idx + 1] == ""
    # La línea previa corresponde al párrafo bajo el cual cae (no es parte del anchor).
    assert "fig-02-01" not in lines_p2[idx - 1]


def test_anchor_figures_alt_text_empty() -> None:
    md = _markdown_with_markers(["p1"], ["p2"])
    fig = _fig(page=2, y_pdf=PAGE_HEIGHT * 0.5)
    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    pages = split_by_page_markers(out)
    line = next(ln for ln in pages[1].splitlines() if "fig-02-01.png" in ln)
    assert line.startswith("![](")
    assert "fig-02-01.png" in line


def test_anchor_figures_custom_prefix() -> None:
    md = _markdown_with_markers(["p1"], ["p2"])
    fig = _fig(page=2, y_pdf=PAGE_HEIGHT * 0.5)

    out = anchor_figures(
        md,
        [fig],
        page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)},
        relative_path_prefix="../images/",
    )

    pages = split_by_page_markers(out)
    assert any("../images/fig-02-01.png" in ln for ln in pages[1].splitlines())


# ---------- CLI integration ----------


@pytest.fixture
def midpage_pdf(tmp_path: Path) -> Path:
    """Fixture literal del roadmap: texto + imagen centrada en página 2."""
    from tests.fixtures.build import build_text_with_midpage_image_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "midpage.pdf"
    build_text_with_midpage_image_pdf(pdf, work)
    return pdf


def _run_convert(args: list[str]) -> object:
    runner = CliRunner()
    return runner.invoke(app, args)


def test_cli_anchor_inserts_image_in_final_markdown(midpage_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    result = _run_convert(["convert", str(midpage_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    # El anchor aparece una sola vez (E5 puede inyectar alt text con caption).
    assert md.count("fig-01-01.png") == 1


def test_cli_no_anchor_skips_insertion(midpage_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"
    result = _run_convert(
        [
            "convert",
            str(midpage_pdf),
            "-o",
            str(out_md),
            "--no-anchor",
        ]
    )

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    assert "fig-01-01.png" not in md  # no anchor insertado
    assert images_dir.is_dir()  # pero el archivo SÍ se generó
    assert any(images_dir.glob("*.png"))


def test_cli_anchor_with_chapter_uses_chapter_index_in_path(tmp_path: Path) -> None:
    """Fixture con outline: --chapter 2 → anchor usa fig-02-01.png."""
    from tests.fixtures.build import build_outline_with_chapter_image_pdf

    pdf = tmp_path / "book.pdf"
    work = tmp_path / "work"
    build_outline_with_chapter_image_pdf(pdf, work)

    out_md = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "convert",
            str(pdf),
            "-o",
            str(out_md),
            "--chapter",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    assert "fig-02-01.png" in md


def test_cli_anchor_with_page_markers_keeps_them(midpage_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    result = _run_convert(
        [
            "convert",
            str(midpage_pdf),
            "-o",
            str(out_md),
            "--page-markers",
        ]
    )

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    assert "<!-- page" in md
    assert "fig-01-01.png" in md
