"""Tests de :func:`capmd.sources.heuristic.detect_chapters` (fase C8).

Cubre los 3 patrones de texto (inglés, español, numérico), fallback a
font-size, casos negativos (PDF sin headings detectables) y garantías
del modelo ``Chapter`` retornado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.errors import ChapterDetectionFailed
from capmd.models import Chapter
from capmd.sources.heuristic import detect_chapters
from tests.fixtures import build


def _no_outline_pdf(tmp_path: Path, **kwargs) -> Path:
    return build.build_no_outline_chapters_pdf(tmp_path / "no_outline.pdf", **kwargs)


def test_detect_by_text_pattern_english(tmp_path: Path) -> None:
    pdf = _no_outline_pdf(tmp_path)
    chapters = detect_chapters(pdf)
    assert len(chapters) == 3
    assert [c.title for c in chapters] == [
        "Chapter 1: Getting Started",
        "Chapter 2: Ownership",
        "Chapter 3: Borrowing",
    ]


def test_detect_by_text_pattern_spanish(tmp_path: Path) -> None:
    pdf = _no_outline_pdf(tmp_path, label="spanish")
    chapters = detect_chapters(pdf)
    assert len(chapters) == 3
    assert all("Capítulo" in c.title for c in chapters)


def test_detect_by_text_pattern_numeric(tmp_path: Path) -> None:
    pdf = _no_outline_pdf(tmp_path, label="numeric")
    chapters = detect_chapters(pdf)
    assert len(chapters) == 3
    assert all(c.title.startswith(("1. ", "2. ", "3. ")) for c in chapters)


def test_detect_returns_chapter_instances_with_level_1(tmp_path: Path) -> None:
    pdf = _no_outline_pdf(tmp_path)
    for ch in detect_chapters(pdf):
        assert isinstance(ch, Chapter)
        assert ch.level == 1


def test_detect_index_sequential(tmp_path: Path) -> None:
    pdf = _no_outline_pdf(tmp_path)
    chapters = detect_chapters(pdf)
    assert [c.index for c in chapters] == [1, 2, 3]


def test_detect_start_pages_match_one_indexed(tmp_path: Path) -> None:
    pdf = _no_outline_pdf(tmp_path)
    chapters = detect_chapters(pdf)
    assert [c.start_page for c in chapters] == [1, 2, 3]


def test_detect_falls_back_to_font_size_when_text_fails(tmp_path: Path) -> None:
    """PDF sin 'Chapter N' en el texto → la heurística de font-size detecta los headings."""
    pdf = _no_outline_pdf(
        tmp_path,
        titles=("Introduction", "Background", "Conclusion"),
    )
    chapters = detect_chapters(pdf)
    assert len(chapters) == 3
    # start_pages contiguos desde 1.
    assert [c.start_page for c in chapters] == [1, 2, 3]


def test_detect_handles_single_chapter(tmp_path: Path) -> None:
    """Un solo heading detectable → devuelve 1 entrada, no falla."""
    pdf = _no_outline_pdf(tmp_path, titles=("Chapter 1: The Only One",))
    chapters = detect_chapters(pdf)
    assert len(chapters) == 1
    assert chapters[0].title == "Chapter 1: The Only One"


def test_detect_raises_when_no_chapters_found(tmp_path: Path) -> None:
    """PDF uniforme sin headings → ChapterDetectionFailed con hint sobre --pages."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as cm

    pdf = tmp_path / "uniform.pdf"
    _, height = LETTER
    c = cm.Canvas(str(pdf), pagesize=LETTER)
    for n in range(1, 4):
        c.setFont("Helvetica", 11)
        c.drawString(72, height - 72, f"Page {n}: same body text without headings.")
        c.showPage()
    c.save()

    with pytest.raises(ChapterDetectionFailed) as excinfo:
        detect_chapters(pdf)
    assert "--pages" in str(excinfo.value.hint)


def test_detect_ignores_body_text_references_to_chapter(tmp_path: Path) -> None:
    """Una mención 'Chapter 5' en el cuerpo no debe matchear como heading.

    Limitamos al primer fragmento de la página (los headings están al
    principio), así que 'Chapter 5' dentro del cuerpo no genera match.
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as cm

    pdf = tmp_path / "body.pdf"
    _, height = LETTER
    c = cm.Canvas(str(pdf), pagesize=LETTER)
    # Página 1: heading real.
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 72, "Chapter 1: Real Heading")
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 100, "Body content.")
    c.showPage()
    # Página 2: solo cuerpo con "Chapter 5" mencionado.
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 72, "In Chapter 5 we discussed something.")
    c.drawString(72, height - 100, "More body content.")
    c.showPage()
    c.save()

    chapters = detect_chapters(pdf)
    assert len(chapters) == 1
    assert chapters[0].start_page == 1
