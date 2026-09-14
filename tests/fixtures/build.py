"""Builders de PDFs sintéticos para tests.

Cada `build_*_pdf(out_path[, work_dir]) -> Path` escribe un PDF determinista
y devuelve la misma ruta. Usados por tests/test_fixtures.py y por fixtures
de fases siguientes (B+, C+, D+).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

__all__ = [
    "ALL_BUILDERS",
    "build_cut_hyphens_pdf",
    "build_epub_with_3_chapters",
    "build_header_footer_pdf",
    "build_headings_pdf",
    "build_many_pages_pdf",
    "build_no_outline_chapters_pdf",
    "build_outline_toc_pdf",
    "build_table_pdf",
    "build_two_images_pdf",
]

Image.MAX_IMAGE_PIXELS = None


def _save_color_square(path: Path, rgb: tuple[int, int, int], size: int = 200) -> Path:
    Image.new("RGB", (size, size), rgb).save(path, format="PNG")
    return path


def build_headings_pdf(out_path: Path) -> Path:
    """PDF con jerarquía H1/H2/H3 via Paragraph styles."""
    doc = SimpleDocTemplate(str(out_path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Chapter 1: Introduction", styles["Heading1"]),
        Paragraph("Body under H1.", styles["BodyText"]),
        Paragraph("1.1 Background", styles["Heading2"]),
        Paragraph("Background content.", styles["BodyText"]),
        Paragraph("1.1.1 Details", styles["Heading3"]),
        Paragraph("Details content.", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Chapter 2: Ownership", styles["Heading1"]),
        Paragraph("Ownership content.", styles["BodyText"]),
        Paragraph("2.1 Borrowing", styles["Heading2"]),
        Paragraph("Borrowing content.", styles["BodyText"]),
    ]
    doc.build(story)
    return out_path


def _draw_header_footer(c: canvas_module.Canvas, text: str) -> None:
    c.saveState()
    width, height = LETTER
    c.setFont("Helvetica", 9)
    c.drawString(36, 36, f"— {c.getPageNumber()} —")
    c.drawCentredString(width / 2, height - 30, text)
    c.restoreState()


def build_header_footer_pdf(out_path: Path) -> Path:
    """PDF con el mismo header/footer en cada página (target de D4)."""
    text = "Capítulo 3 | Rust in Action"

    def _on(c: canvas_module.Canvas, doc: SimpleDocTemplate) -> None:
        _draw_header_footer(c, text)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        onFirstPage=_on,
        onLaterPages=_on,
    )
    styles = getSampleStyleSheet()
    body = Paragraph("Body " * 80, styles["BodyText"])
    story = []
    for label in ("A", "B", "C", "D"):
        story.append(Paragraph(f"Section {label}", styles["Heading1"]))
        story.append(body)
    doc.build(story)
    return out_path


def build_cut_hyphens_pdf(out_path: Path) -> Path:
    """PDF con palabras cortadas con guion al final de línea (target D3)."""
    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER
    y = height - 72
    c.setFont("Helvetica", 11)
    lines = [
        "The know-",
        "ledge of programming helps.",
        "The pala-",
        "bra of pala-",
        "bra-like words survives.",
        "Compound well-known",
        "terms must NOT be joined.",
        "Page two: conti-",
        "nuation text continues.",
    ]
    for line in lines:
        c.drawString(72, y, line)
        y -= 14
        if y < 72:
            c.showPage()
            y = height - 72
    c.save()
    return out_path


def build_two_images_pdf(out_path: Path, work_dir: Path) -> Path:
    """PDF con exactamente 2 imágenes embebidas. `work_dir` recibe los PNGs."""
    work_dir.mkdir(parents=True, exist_ok=True)
    _save_color_square(work_dir / "fig-red.png", (220, 50, 50))
    _save_color_square(work_dir / "fig-blue.png", (50, 80, 220))

    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, height - 72, "Figure 3.1 — Red square")
    c.drawImage(
        str(work_dir / "fig-red.png"),
        72,
        height - 320,
        width=200,
        height=200,
        preserveAspectRatio=True,
    )
    c.drawString(72, height - 360, "Figure 3.2 — Blue square")
    c.drawImage(
        str(work_dir / "fig-blue.png"),
        72,
        height - 600,
        width=200,
        height=200,
        preserveAspectRatio=True,
    )
    c.save()
    return out_path


def build_table_pdf(out_path: Path) -> Path:
    """PDF con tabla 3x4 estructurada (target D12)."""
    doc = SimpleDocTemplate(str(out_path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    data = [
        ["Header A", "Header B", "Header C"],
        ["row 1 a", "row 1 b", "row 1 c"],
        ["row 2 a", "row 2 b", "row 2 c"],
        ["row 3 a", "row 3 b", "row 3 c"],
    ]
    table = Table(data, colWidths=[150, 150, 150])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story = [
        Paragraph("Sample Table", styles["Heading1"]),
        Spacer(1, 12),
        table,
    ]
    doc.build(story)
    return out_path


def build_many_pages_pdf(out_path: Path, n_pages: int = 500) -> Path:
    """PDF sintético de N páginas con texto mínimo (target B5).

    Usa ``canvas.Canvas`` directo (no ``SimpleDocTemplate``) para no
    inflar el fixture: cada página pesa pocos cientos de bytes. El
    default ``n_pages=500`` es el valor literal del test del roadmap
    B5 ("PDF de 500 páginas sintéticas convierte sin explotar la
    memoria y reporta el tiempo").
    """
    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER
    body = ("Body content for page. " * 20).strip()
    for page_num in range(1, n_pages + 1):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, height - 72, f"Page {page_num}")
        c.setFont("Helvetica", 11)
        c.drawString(72, height - 100, body)
        c.showPage()
    c.save()
    return out_path


def build_outline_toc_pdf(out_path: Path) -> Path:
    """PDF con outline/TOC embebido (target C1)."""
    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER

    def chapter_page(
        key: str,
        title: str,
        sub: list[tuple[str, str]] | None = None,
    ) -> None:
        y = height - 72
        c.bookmarkPage(key)
        c.addOutlineEntry(title, key, level=0, closed=False)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(72, y, title)
        y -= 28
        c.setFont("Helvetica", 11)
        c.drawString(72, y, f"Content of {title}.")
        if sub:
            y -= 22
            for sub_key, sub_title in sub:
                c.bookmarkPage(sub_key)
                c.addOutlineEntry(sub_title, sub_key, level=1, closed=False)
                c.setFont("Helvetica-Bold", 14)
                c.drawString(72, y, sub_title)
                y -= 18
                c.setFont("Helvetica", 11)
                c.drawString(72, y, f"Content of {sub_title}.")
        c.showPage()

    chapter_page("ch1", "Chapter 1: Getting Started", sub=[("ch1s1", "1.1 Background")])
    chapter_page("ch2", "Chapter 2: Ownership")
    chapter_page("ch3", "Chapter 3: Borrowing")
    c.save()
    return out_path


def build_no_outline_chapters_pdf(
    out_path: Path,
    *,
    titles: tuple[str, ...] = (
        "Chapter 1: Getting Started",
        "Chapter 2: Ownership",
        "Chapter 3: Borrowing",
    ),
    label: str = "english",
) -> Path:
    """PDF con capítulos detectables pero SIN outline embebido (target C8).

    Usa ``canvas.Canvas`` directo (sin ``SimpleDocTemplate``) para no
    generar outline implícito. Cada capítulo ocupa una página con
    heading a 18pt y cuerpo a 11pt — la heurística de font-size los
    detecta por el salto de tamaño.

    ``label`` admite ``"english"`` (titles por default), ``"spanish"``
    (prefix "Capítulo N") y ``"numeric"`` (prefix "N. Title"). Para
    tests negativos (``titles=("Introduction", "Conclusion")`` sin
    patrón numérico ni "Chapter") se usa la heurística de font-size.
    """
    if label == "spanish":
        titles = tuple(f"Capítulo {i + 1}: {t.split(': ', 1)[-1]}" for i, t in enumerate(titles))
    elif label == "numeric":
        titles = tuple(f"{i + 1}. {t.split(': ', 1)[-1]}" for i, t in enumerate(titles))

    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER
    for title in titles:
        c.setFont("Helvetica-Bold", 18)
        c.drawString(72, height - 72, title)
        c.setFont("Helvetica", 11)
        c.drawString(72, height - 100, f"Body content of {title}.")
        c.showPage()
    c.save()
    return out_path


def build_epub_with_3_chapters(out_path: Path) -> Path:
    """EPUB3 con 3 capítulos XHTML, NCX y nav (target C9).

    Usa ``ebooklib.epub.EpubBook`` que escribe un EPUB válido
    (requiere NCX + nav items explícitos en 0.20). Cada capítulo tiene
    un marcador único ``MARKER-CH-N-CONTENT`` para que los tests
    puedan verificar que solo se incluyó el correcto.
    """
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("capmd-fixture-epub-3ch")
    book.set_title("Capmd Test EPUB")
    book.set_language("es")
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    def chapter(num: int, fname: str) -> epub.EpubHtml:
        content = (
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<body><h1>Capitulo {num}: Capitulo {num}</h1>"
            f"<p>Body of chapter {num}. MARKER-CH-{num}-CONTENT.</p>"
            "</body></html>"
        ).encode()
        return epub.EpubHtml(title=f"Capitulo {num}", file_name=fname, content=content)

    ch1 = chapter(1, "ch1.xhtml")
    ch2 = chapter(2, "ch2.xhtml")
    ch3 = chapter(3, "ch3.xhtml")
    book.add_item(ch1)
    book.add_item(ch2)
    book.add_item(ch3)
    book.toc = (ch1, ch2, ch3)
    book.spine = ["nav", ch1, ch2, ch3]

    epub.write_epub(str(out_path), book)
    return out_path


ALL_BUILDERS = [
    build_headings_pdf,
    build_header_footer_pdf,
    build_cut_hyphens_pdf,
    build_two_images_pdf,
    build_table_pdf,
    build_outline_toc_pdf,
    build_many_pages_pdf,
    build_no_outline_chapters_pdf,
    build_epub_with_3_chapters,
]
