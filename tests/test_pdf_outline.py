"""Tests del lector de outline de PDF (fase C1).

Contrato:

- ``read_outline`` devuelve ``list[Chapter]`` en orden DFS, con páginas
  1-indexed, ``level`` 1-indexed desde la raíz, e ``index`` secuencial.
- ``read_outline_tuples`` es el alias ``(level, title, page)`` del roadmap.
- PDFs sin outline → ``[]``.
- Archivos inexistentes / corruptos → ``SourceNotFound``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from capmd.errors import ChapterDetectionFailed, SourceNotFound
from capmd.sources.pdf import (
    Chapter,
    read_outline,
    read_outline_tuples,
    read_outline_with_fallback,
)
from tests.fixtures import build

# El fixture ``build_outline_toc_pdf`` produce:
#   page 1: "Chapter 1: Getting Started"  (con subentrada "1.1 Background")
#   page 2: "Chapter 2: Ownership"
#   page 3: "Chapter 3: Borrowing"
# Confirmamos el contrato mirando qué título arranca cada página real del PDF,
# así los tests no se rompen si reportlab cambia el layout interno.
EXPECTED_TITLES = [
    "Chapter 1: Getting Started",
    "1.1 Background",
    "Chapter 2: Ownership",
    "Chapter 3: Borrowing",
]


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "outline_toc.pdf")


def test_read_outline_returns_chapters_in_order(tmp_path: Path) -> None:
    chapters = read_outline(_outline_pdf(tmp_path))
    titles = [c.title for c in chapters]
    assert titles == EXPECTED_TITLES


def test_read_outline_levels(tmp_path: Path) -> None:
    chapters = read_outline(_outline_pdf(tmp_path))
    levels = [c.level for c in chapters]
    assert levels == [1, 2, 1, 1]


def test_read_outline_pages_are_one_indexed_and_match_first_line(
    tmp_path: Path,
) -> None:
    chapters = read_outline(_outline_pdf(tmp_path))

    # Cada entrada nivel-1 debe arrancar en la página cuya primera
    # línea no vacía es su título. Las subentradas pueden compartir
    # página con el padre (el fixture dibuja H1 y H1.1 en la misma
    # hoja), así que para ellas validamos que el texto aparezca en la
    # página, no que sea la primera línea.
    reader = PdfReader(str(_outline_pdf(tmp_path)))
    for c in chapters:
        page_text = reader.pages[c.start_page - 1].extract_text() or ""
        if c.level == 1:
            first_line = next((ln for ln in page_text.splitlines() if ln.strip()), "")
            assert c.title == first_line, (
                f"page {c.start_page} starts with {first_line!r}, expected {c.title!r}"
            )
        else:
            assert c.title in page_text, (
                f"page {c.start_page} does not contain subheading {c.title!r}"
            )


def test_read_outline_tuples_alias(tmp_path: Path) -> None:
    tuples = read_outline_tuples(_outline_pdf(tmp_path))
    assert tuples == [
        (1, "Chapter 1: Getting Started", 1),
        (2, "1.1 Background", 1),
        (1, "Chapter 2: Ownership", 2),
        (1, "Chapter 3: Borrowing", 3),
    ]


def test_read_outline_empty_pdf_returns_empty_list(tmp_path: Path) -> None:
    p = build.build_headings_pdf(tmp_path / "headings.pdf")
    assert read_outline(p) == []


def test_read_outline_missing_file_raises_source_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "no-existe.pdf"
    with pytest.raises(SourceNotFound):
        read_outline(missing)


def test_read_outline_index_is_sequential(tmp_path: Path) -> None:
    chapters = read_outline(_outline_pdf(tmp_path))
    assert [c.index for c in chapters] == list(range(1, len(chapters) + 1))


def test_read_outline_returns_chapter_instances(tmp_path: Path) -> None:
    chapters = read_outline(_outline_pdf(tmp_path))
    assert all(isinstance(c, Chapter) for c in chapters)
    # Sanity: el modelo se respeta (frozen, level >= 1, etc.).
    assert all(c.level >= 1 for c in chapters)
    assert all(c.start_page >= 1 for c in chapters)
    assert all(c.end_page == c.start_page for c in chapters)  # provisional C1


# --- C8: read_outline_with_fallback ---------------------------------------


def _no_outline_pdf(tmp_path: Path) -> Path:
    return build.build_no_outline_chapters_pdf(tmp_path / "no_outline.pdf")


def test_fallback_uses_heuristic_when_outline_empty(tmp_path: Path) -> None:
    chapters = read_outline_with_fallback(_no_outline_pdf(tmp_path))
    assert [c.title for c in chapters] == [
        "Chapter 1: Getting Started",
        "Chapter 2: Ownership",
        "Chapter 3: Borrowing",
    ]


def test_fallback_prefers_outline_when_present(tmp_path: Path) -> None:
    """PDF con outline → devuelve el outline, no invoca la heurística."""
    chapters = read_outline_with_fallback(_outline_pdf(tmp_path))
    titles = [c.title for c in chapters]
    # El outline tiene 4 entradas con títulos conocidos; la heurística
    # también detectaría los capítulos pero el outline gana.
    assert titles == EXPECTED_TITLES


def test_fallback_propagates_chapter_detection_failed(tmp_path: Path) -> None:
    """PDF sin outline ni heurística posible → ChapterDetectionFailed."""
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

    with pytest.raises(ChapterDetectionFailed):
        read_outline_with_fallback(bad)
