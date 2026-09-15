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
    "build_logo_repeated_pdf",
    "build_many_pages_pdf",
    "build_no_outline_chapters_pdf",
    "build_outline_toc_pdf",
    "build_outline_with_chapter_image_pdf",
    "build_table_pdf",
    "build_text_with_midpage_image_pdf",
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
    """PDF con el mismo header/footer en cada página (target de D4).

    Genera 4 páginas forzando saltos con ``PageBreak``. Cada página
    lleva el header centrado ``Capítulo 3 | Rust in Action`` y el
    footer centrado ``— N —``.
    """
    from reportlab.platypus import PageBreak

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
    body = Paragraph(
        "Body text to fill the page so D4 has multiple pages with "
        "repeated headers and footers to detect. " * 20,
        styles["BodyText"],
    )
    story = []
    for label in ("A", "B", "C", "D"):
        story.append(Paragraph(f"Section {label}", styles["Heading1"]))
        story.append(body)
        if label != "D":
            story.append(PageBreak())
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


def build_outline_with_chapter_image_pdf(out_path: Path, work_dir: Path) -> Path:
    """Outline de 3 capítulos + una imagen embebida en la página 2 (capítulo 2).

    Útil para tests que verifican ``--chapter 2`` y la propagación del
    índice numérico del capítulo al nombre de las imágenes extraídas
    (E3). Solo el capítulo "Chapter 2: Ownership" lleva una imagen
    adjunta; los otros capítulos tienen solo texto.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    image_path = work_dir / "chapter2-fig.png"
    _save_color_square(image_path, (40, 160, 90), size=180)

    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER

    # Página 1 — Chapter 1: Getting Started
    c.bookmarkPage("ch1")
    c.addOutlineEntry("Chapter 1: Getting Started", "ch1", level=0, closed=False)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 72, "Chapter 1: Getting Started")
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 100, "Content of chapter 1.")
    c.showPage()

    # Página 2 — Chapter 2: Ownership (con imagen embebida)
    c.bookmarkPage("ch2")
    c.addOutlineEntry("Chapter 2: Ownership", "ch2", level=0, closed=False)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 72, "Chapter 2: Ownership")
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 100, "Content of chapter 2 with figure.")
    c.drawImage(
        str(image_path),
        x=72,
        y=height - 360,
        width=180,
        height=180,
        preserveAspectRatio=True,
    )
    c.showPage()

    # Página 3 — Chapter 3: Borrowing
    c.bookmarkPage("ch3")
    c.addOutlineEntry("Chapter 3: Borrowing", "ch3", level=0, closed=False)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 72, "Chapter 3: Borrowing")
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 100, "Content of chapter 3.")
    c.showPage()

    c.save()
    return out_path


_LOGO_SIZE = 50
_LOGO_FIG_SIZE = 200


def build_logo_repeated_pdf(
    out_path: Path,
    work_dir: Path,
    *,
    n_pages: int = 4,
) -> Path:
    """PDF con un logo en cada página + figuras reales intercaladas (target E2).

    Layout por página:
      - Esquina superior izquierda: logo (50x50 px) — idéntico en todas las páginas.
      - Cuerpo: tres líneas de texto Helvetica 11.
      - Páginas 2 y 4 (1-indexed): además, una figura real 200x200 en el centro.

    Con los defaults de :class:`FilterRules` (min_size=64x64,
    repeat_threshold=0.8, background_coverage=0.85), tras filtrar deben
    quedar exactamente 2 figuras (las reales de las páginas 2 y 4).
    El logo aparece en 4/4 = 100% > 0.8 → su primera aparición (página 1)
    cae por TOO_SMALL primero, así que no se conserva siquiera la primera.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    logo_path = work_dir / "logo.png"
    red_fig_path = work_dir / "real-red.png"
    blue_fig_path = work_dir / "real-blue.png"

    _save_color_square(logo_path, (40, 40, 40), size=_LOGO_SIZE)
    _save_color_square(red_fig_path, (220, 50, 50), size=_LOGO_FIG_SIZE)
    _save_color_square(blue_fig_path, (50, 80, 220), size=_LOGO_FIG_SIZE)

    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER
    page_width, _ = LETTER

    for page_num in range(1, n_pages + 1):
        c.setFont("Helvetica", 11)
        for line in range(3):
            c.drawString(
                72, height - 100 - 14 * line, f"Body content of page {page_num}, line {line + 1}."
            )

        c.drawImage(
            str(logo_path),
            x=page_width - 72 - _LOGO_SIZE,
            y=height - 72 - _LOGO_SIZE,
            width=_LOGO_SIZE,
            height=_LOGO_SIZE,
            preserveAspectRatio=True,
            mask="auto",
        )

        if page_num == 2:
            c.drawImage(
                str(red_fig_path),
                x=72,
                y=height // 2 - _LOGO_FIG_SIZE // 2,
                width=_LOGO_FIG_SIZE,
                height=_LOGO_FIG_SIZE,
                preserveAspectRatio=True,
            )
        elif page_num == 4:
            c.drawImage(
                str(blue_fig_path),
                x=72,
                y=height // 2 - _LOGO_FIG_SIZE // 2,
                width=_LOGO_FIG_SIZE,
                height=_LOGO_FIG_SIZE,
                preserveAspectRatio=True,
            )

        c.showPage()

    c.save()
    return out_path


def _draw_inline_image(image_path: Path):
    """Callback legacy; el fixture moderno ya no usa callbacks — ver
    ``build_text_with_midpage_image_pdf``. Se mantiene por compatibilidad
    con tests que referenciaban el nombre. La imagen se embebe directamente
    vía ``canvas.Canvas.drawImage`` para que pypdfium2 la exponga como
    objeto de tipo imagen."""
    raise NotImplementedError(
        "use canvas.Canvas.drawImage directly; see build_text_with_midpage_image_pdf"
    )


def build_text_with_midpage_image_pdf(
    out_path: Path,
    work_dir: Path,
    *,
    n_paras_page2: int = 5,
    caption: str | None = "Figura 3.1 — Diagrama de la imagen central",
) -> Path:
    """PDF de 2 páginas con texto narrativo y una imagen centrada verticalmente
    en la página 2 (target E4 + E5).

    Página 1: heading + 3 párrafos de body, sin imágenes.
    Página 2: heading + ``n_paras_page2`` párrafos numerados + imagen
    de 200x200 a mitad de la página + (caption opcional) + 1 párrafo final.

    La imagen se embebe con ``canvas.Canvas.drawImage`` para que
    pypdfium2 la exponga como objeto de tipo ``FPDF_PAGEOBJ_IMAGE``
    y la extracción (E1) la detecte correctamente.

    Para que ``text extraction`` siga produciendo markdown coherente, los
    párrafos se renderizan como texto plano encima de la imagen. Si
    se pasa ``caption=None``, no se dibuja caption (target E5 imagen
    sin caption).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    image_path = work_dir / "midpage-fig.png"
    _save_color_square(image_path, (50, 130, 200), size=200)

    c = canvas_module.Canvas(str(out_path), pagesize=LETTER)
    _, height = LETTER

    # Página 1 — heading + 3 párrafos.
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 72, "Chapter X: Heading on page 1")
    c.setFont("Helvetica", 11)
    y = height - 100
    for i in range(1, 4):
        c.drawString(72, y, f"This is paragraph {i} on page 1, providing enough text to fill it.")
        y -= 16
    c.showPage()

    # Página 2 — heading + n_paras_page2 párrafos + imagen centrada + trailing.
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 72, "Chapter Y: Heading on page 2 with mid-page figure")
    c.setFont("Helvetica", 11)
    y = height - 100
    for i in range(1, n_paras_page2 + 1):
        c.drawString(72, y, f"Body paragraph number {i} on page 2, providing contextual text.")
        y -= 16

    # Dibuja la imagen centrada verticalmente (≈ y = 296 pts en LETTER).
    img_size = 200
    img_y_bottom = height / 2 - img_size / 2
    c.drawImage(
        str(image_path),
        x=72,
        y=img_y_bottom,
        width=img_size,
        height=img_size,
        preserveAspectRatio=True,
    )

    # Caption (E5): justo debajo de la imagen, en cursiva.
    caption_y = None
    if caption is not None:
        caption_y = img_y_bottom - 14
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(72, caption_y, caption)

    # Párrafo trailing debajo del caption (o de la imagen si no hay caption).
    c.setFont("Helvetica", 11)
    trailing_y = (caption_y - 14) if caption_y is not None else (img_y_bottom - 16)
    c.drawString(72, trailing_y, "Trailing body paragraph on page 2 after the figure.")

    c.showPage()
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
    build_logo_repeated_pdf,
    build_outline_with_chapter_image_pdf,
    build_text_with_midpage_image_pdf,
]
