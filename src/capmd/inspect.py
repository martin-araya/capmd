"""``capmd inspect`` — diagnóstico estructural de un PDF (H3).

Reporta 4 métricas sobre un PDF **sin convertirlo**:

1. **texto/escaneado**: ``words_per_page``. ``scanned=True`` si
   ``words_per_page < 10`` (mismo threshold que el heurístico F6
   ``scanned_pdf`` del :mod:`capmd.report`).
2. **outline**: ``read_outline_with_fallback`` (C1/C8) — reporta origen
   (``outline``, ``heuristic``, ``none``) y los primeros 20 items
   ``(level, title, start_page)``.
3. **fuentes**: enumera las fuentes distintas vía ``pypdfium2``
   ``PdfTextObj.get_font()``, agrupadas por nombre+type.
4. **headers/footers repetidos**: lee top-3/bottom-3 líneas de cada
   página muestreada y reporta las que aparecen en ``>=60%`` de las
   páginas (mismo threshold que :class:`HeaderFooterOptions`).

Para PDFs grandes, las secciones 3 y 4 se limitan a las primeras
``sample`` páginas (default 20) para mantener el run < 1s.

EPUB: solo outline (H3 no soporta fonts/text/headers en EPUB).
DOCX/PPTX/XLSX: ``UnsupportedFormat``.
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium

from capmd.errors import SourceNotFound, UnsupportedFormat

try:
    from rich.panel import Panel as _Panel
except ImportError:  # pragma: no cover - rich es dep declarada
    _Panel = None  # type: ignore[misc, assignment]

__all__ = [
    "FontsInspection",
    "HeadersInspection",
    "InspectionReport",
    "OutlineInspection",
    "inspect_pdf",
    "render_json",
    "render_text",
]

logger = logging.getLogger(__name__)

_SCANNED_THRESHOLD = 10  # words/page; mismo valor que ``report.scanned_pdf``.
_HEADER_LINES = 3
_FOOTER_LINES = 3
_HEADER_THRESHOLD = 0.6
_OUTLINE_ITEM_LIMIT = 20


@dataclass(frozen=True)
class OutlineInspection:
    """Resultado del análisis de outline."""

    source: Literal["outline", "heuristic", "none"]
    count: int
    items: tuple[tuple[int, str, int], ...] = field(default_factory=tuple)
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "source": self.source,
            "count": self.count,
            "items": [list(it) for it in self.items],
        }
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass(frozen=True)
class FontsInspection:
    """Resultado del análisis de fuentes."""

    count: int
    items: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "count": self.count,
            "items": [list(it) for it in self.items],
        }
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass(frozen=True)
class HeadersInspection:
    """Resultado del análisis de headers/footers repetidos."""

    headers: tuple[str, ...] = field(default_factory=tuple)
    footers: tuple[str, ...] = field(default_factory=tuple)
    threshold: float = _HEADER_THRESHOLD
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "headers": list(self.headers),
            "footers": list(self.footers),
            "threshold": self.threshold,
        }
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass(frozen=True)
class InspectionReport:
    """Reporte completo de :func:`inspect_pdf`.

    Todos los sub-bloques (``outline``/``fonts``/``headers``) pueden
    ser ``None`` si el caller pasó ``--no-X`` o si el formato no los
    soporta (ej. EPUB no tiene fonts/headers en H3).
    """

    schema_version: int
    path: str
    format: str
    pages: int | None
    words_total: int | None
    words_per_page: float | None
    scanned: bool | None
    outline: OutlineInspection | None
    fonts: FontsInspection | None
    headers: HeadersInspection | None
    sampled_pages: int | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "schema_version": self.schema_version,
            "path": self.path,
            "format": self.format,
            "pages": self.pages,
            "words_total": self.words_total,
            "words_per_page": (
                round(self.words_per_page, 2)
                if self.words_per_page is not None
                else None
            ),
            "scanned": self.scanned,
            "outline": self.outline.to_dict() if self.outline is not None else None,
            "fonts": self.fonts.to_dict() if self.fonts is not None else None,
            "headers": self.headers.to_dict() if self.headers is not None else None,
            "sampled_pages": self.sampled_pages,
        }
        return d


# ---------------------------------------------------------------------------
# Builder principal
# ---------------------------------------------------------------------------


def inspect_pdf(
    path: Path,
    *,
    sample: int = 20,
    include_outline: bool = True,
    include_text: bool = True,
    include_fonts: bool = True,
    include_headers_footers: bool = True,
) -> InspectionReport:
    """Analiza ``path`` y devuelve un :class:`InspectionReport`.

    Args:
        path: ruta al PDF/EPUB.
        sample: máximo de páginas a muestrear para fonts/headers/footers
            y para el cálculo de ``words_total``. Outline se lee siempre
            completo.
        include_*:开关 por sección; las pasadas como ``False``
            devuelven ``None`` en el reporte.

    Raises:
        SourceNotFound: si ``path`` no existe o no es archivo.
        UnsupportedFormat: si la extensión no es .pdf ni .epub.
    """
    if not path.exists() or not path.is_file():
        raise SourceNotFound(
            f"no se encontró el archivo: {path}",
            hint="verificá la ruta",
        )

    fmt = path.suffix.lower().lstrip(".")
    if fmt == "pdf":
        return _inspect_pdf(path, sample=sample, include_outline=include_outline,
                            include_text=include_text, include_fonts=include_fonts,
                            include_headers_footers=include_headers_footers)
    if fmt == "epub":
        return _inspect_epub(path, include_outline=include_outline)
    raise UnsupportedFormat(
        f"capmd inspect no soporta {path.suffix!r}",
        hint="H3 acepta PDF y EPUB; otros formatos usan ``capmd convert``",
    )


def _inspect_pdf(
    path: Path,
    *,
    sample: int,
    include_outline: bool,
    include_text: bool,
    include_fonts: bool,
    include_headers_footers: bool,
) -> InspectionReport:
    pages: int | None = None
    words_total: int | None = None
    scanned: bool | None = None
    font_items: tuple[tuple[str, str], ...] = ()
    fonts_error: str | None = None
    headers_items: tuple[str, ...] = ()
    footers_items: tuple[str, ...] = ()
    headers_error: str | None = None

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        return _error_report(path, "pdf", exc)

    try:
        pages = len(pdf)
        words_total = 0
        # Lista de (page_idx, texto_normalizado_por_linea) para headers/footers.
        per_page_lines: list[tuple[int, list[str]]] = []
        n_sample = min(sample, pages) if pages else 0
        for i in range(n_sample):
            page = pdf[i]
            try:
                tp = page.get_textpage()
                text = tp.get_text_range() or ""
            except Exception:
                text = ""
            words_total += _count_words(text)

            if include_headers_footers:
                lines = _split_lines(text)
                per_page_lines.append((i + 1, lines))

            if include_fonts:
                try:
                    font_items = _collect_fonts(pdf, n_pages=n_sample)
                except Exception as exc:
                    fonts_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        return _error_report(path, "pdf", exc)
    finally:
        pdf.close()

    if include_text:
        wpp = (words_total / pages) if pages else 0.0
        scanned = pages > 0 and wpp < _SCANNED_THRESHOLD
    else:
        wpp = None

    if include_headers_footers and per_page_lines:
        try:
            headers_items, footers_items = _detect_repeating_borders(
                per_page_lines,
                threshold=_HEADER_THRESHOLD,
            )
        except Exception as exc:
            headers_error = f"{type(exc).__name__}: {exc}"

    return InspectionReport(
        schema_version=1,
        path=str(path),
        format="pdf",
        pages=pages,
        words_total=words_total if include_text else None,
        words_per_page=wpp,
        scanned=scanned,
        outline=_inspect_pdf_outline(path) if include_outline else None,
        fonts=(
            FontsInspection(count=len(font_items), items=font_items, error=fonts_error)
            if include_fonts
            else None
        ),
        headers=(
            HeadersInspection(
                headers=headers_items,
                footers=footers_items,
                threshold=_HEADER_THRESHOLD,
                error=headers_error,
            )
            if include_headers_footers
            else None
        ),
        sampled_pages=n_sample if (include_fonts or include_headers_footers) else None,
    )


def _error_report(path: Path, fmt: str, exc: Exception) -> InspectionReport:
    msg = f"{type(exc).__name__}: {exc}"
    return InspectionReport(
        schema_version=1,
        path=str(path),
        format=fmt,
        pages=None,
        words_total=None,
        words_per_page=None,
        scanned=None,
        outline=None,
        fonts=None,
        headers=HeadersInspection(error=msg),
        sampled_pages=None,
    )


def _inspect_pdf_outline(path: Path) -> OutlineInspection:
    try:
        from capmd.sources.pdf import read_outline_with_fallback
    except ImportError as exc:
        return OutlineInspection(
            source="none", count=0, error=f"import failed: {exc}"
        )
    try:
        chapters = read_outline_with_fallback(path)
    except Exception as exc:
        return OutlineInspection(
            source="none", count=0, error=f"{type(exc).__name__}: {exc}"
        )
    if not chapters:
        return OutlineInspection(source="none", count=0)
    # Distinguir outline vs heurística por la presencia de metadata "raw".
    # C1 detecta origen real; C8 (heurística) no tiene acceso al /Outlines.
    try:
        from pypdf import PdfReader

        has_outline = bool(PdfReader(str(path)).outline)
    except Exception:
        has_outline = False
    source: Literal["outline", "heuristic"]
    source = "outline" if has_outline else "heuristic"

    items = tuple(
        (ch.level, ch.title, ch.start_page) for ch in chapters[:_OUTLINE_ITEM_LIMIT]
    )
    return OutlineInspection(source=source, count=len(chapters), items=items)


def _inspect_epub(path: Path, *, include_outline: bool) -> InspectionReport:
    outline: OutlineInspection | None = None
    if include_outline:
        try:
            from capmd.sources.epub import read_outline as read_outline_epub

            chapters = read_outline_epub(path)
        except Exception as exc:
            outline = OutlineInspection(
                source="none", count=0, error=f"{type(exc).__name__}: {exc}"
            )
        else:
            items = tuple(
                (ch.level, ch.title, ch.start_page) for ch in chapters[:_OUTLINE_ITEM_LIMIT]
            )
            outline = OutlineInspection(
                source="outline", count=len(chapters), items=items
            )

    return InspectionReport(
        schema_version=1,
        path=str(path),
        format="epub",
        pages=None,
        words_total=None,
        words_per_page=None,
        scanned=None,
        outline=outline,
        # EPUB sin fonts/headers en H3 (se documenta en --help).
        fonts=None,
        headers=None,
        sampled_pages=None,
    )


# ---------------------------------------------------------------------------
# Helpers de extracción
# ---------------------------------------------------------------------------


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_line(s: str) -> str:
    return _WHITESPACE_RE.sub(" ", s).strip()


def _count_words(text: str) -> int:
    return len(text.split())


def _split_lines(text: str) -> list[str]:
    return [_normalize_line(ln) for ln in text.splitlines() if _normalize_line(ln)]


def _collect_fonts(pdf: pdfium.PdfDocument, *, n_pages: int) -> tuple[tuple[str, str], ...]:
    """Enumera fuentes únicas en las primeras ``n_pages`` páginas.

    Devuelve tuplas ``(font_name, font_type_str)`` ordenadas. Usa
    ``PdfTextObj.get_font()`` que devuelve un :class:`pypdfium2.PdfFont`;
    extraemos ``base_name`` y ``weight`` (heurística lightweight).
    """
    items: set[tuple[str, str]] = set()
    for i in range(n_pages):
        page = pdf[i]
        try:
            tp = page.get_textpage()
        except Exception:
            continue
        n = tp.count_chars()
        for j in range(n):
            try:
                obj = tp.get_textobj(j)
            except Exception:
                continue
            if obj is None:
                continue
            try:
                font = obj.get_font()
            except Exception:
                continue
            try:
                base = font.get_base_name() or ""
            except Exception:
                base = ""
            try:
                weight = font.get_weight() or 0
            except Exception:
                weight = 0
            if not base:
                continue
            if weight >= 700:
                ftype = "Bold"
            elif 400 < weight < 700:
                ftype = "Medium"
            else:
                ftype = "Regular"
            items.add((base, ftype))
    return tuple(sorted(items))


def _detect_repeating_borders(
    per_page_lines: list[tuple[int, list[str]]],
    *,
    threshold: float,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Detecta líneas que aparecen en ``>= threshold`` de páginas como header o footer.

    ``per_page_lines`` es una lista de ``(page_num, [normalized_lines])``.
    Consideramos las primeras ``_HEADER_LINES`` y las últimas
    ``_FOOTER_LINES`` de cada página (excluyendo intersección).
    """
    n = len(per_page_lines)
    if n < 2:
        return (), ()

    threshold_count = max(1, int(threshold * n + 0.5))
    header_counter: Counter[str] = Counter()
    footer_counter: Counter[str] = Counter()
    page_numbers = {line for _pn, lines in per_page_lines for line in lines if line.isdigit()}

    for _pn, lines in per_page_lines:
        top = lines[:_HEADER_LINES]
        bottom = lines[-_FOOTER_LINES:] if len(lines) > _HEADER_LINES else []
        top_set = set(top)
        for line in top:
            # Filtrar líneas que son solo número de página (heurística D6).
            if line in page_numbers:
                continue
            key = _normalize_line(line)
            if key:
                header_counter[key] += 1
        for line in bottom:
            if line in top_set:
                continue
            if line in page_numbers:
                continue
            key = _normalize_line(line)
            if key:
                footer_counter[key] += 1

    headers = tuple(sorted(k for k, c in header_counter.items() if c >= threshold_count))
    footers = tuple(sorted(k for k, c in footer_counter.items() if c >= threshold_count))
    return headers, footers


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_json(report: InspectionReport) -> str:
    """Serializa el reporte como JSON parseable."""
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=False)


def _check(ok: bool) -> str:
    return "[OK]" if ok else "[WARN]"


def render_text(report: InspectionReport) -> str:
    """Renderiza el reporte en formato human-readable con rich."""
    try:
        from rich.console import Console
        from rich.panel import Panel
    except ImportError:  # pragma: no cover - rich es dep declarada
        return _render_text_plain(report)

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=88)

    console.print(
        Panel(
            f"[bold]{report.path}[/bold]  [dim]({report.format})[/dim]",
            border_style="cyan",
        )
    )

    # Texto / escaneado
    if report.format == "epub":
        console.print(_section_text_epub())
    else:
        console.print(_section_text_pdf(report))

    if report.outline is not None:
        console.print(_section_outline(report.outline))

    if report.fonts is not None:
        console.print(_section_fonts(report.fonts))

    if report.headers is not None:
        console.print(_section_headers(report.headers))

    if (
        report.sampled_pages is not None
        and report.pages is not None
        and report.sampled_pages < report.pages
    ):
        console.print(
            f"\n[dim]sample: {report.sampled_pages} de {report.pages} páginas[/dim]"
        )

    return buf.getvalue()


def _render_text_plain(report: InspectionReport) -> str:
    parts: list[str] = [f"=== {report.path} ({report.format}) ==="]
    if report.words_per_page is not None:
        wpp = report.words_per_page
        scanned = report.scanned
        flag = "[WARN] PDF parece escaneado" if scanned else "[OK] PDF con texto embebido"
        parts.append(f"texto: {flag} (words/page={wpp:.1f})")
    if report.outline is not None:
        if report.outline.error:
            parts.append(f"outline: error {report.outline.error}")
        else:
            parts.append(f"outline: {report.outline.source}, {report.outline.count} caps")
    if report.fonts is not None:
        parts.append(f"fonts: {report.fonts.count} distintas")
    if report.headers is not None:
        parts.append(
            f"headers/footers: {len(report.headers.headers)}/{len(report.headers.footers)}"
        )
    return "\n".join(parts)


def _section_text_pdf(report: InspectionReport) -> _Panel:
    body = (
        f"[WARN] PDF parece escaneado: {report.words_total or 0} palabras "
        f"en {report.pages or 0} páginas (words/page<{_SCANNED_THRESHOLD})"
        if report.scanned
        else (
            f"[OK] PDF con texto embebido: "
            f"{report.words_total} palabras en {report.pages} páginas "
            f"(words/page={report.words_per_page or 0.0:.1f})"
        )
    )
    if report.scanned:
        body += "\n[dim]sugerencia: instalá markitdown-ocr para hacer OCR[/dim]"
    return _Panel(body, title="texto", border_style="cyan")


def _section_text_epub() -> _Panel:
    body = "[dim]EPUB: solo outline soportado en H3[/dim]"
    return _Panel(body, title="texto", border_style="cyan")


def _section_outline(oi: OutlineInspection) -> _Panel:
    if oi.error:
        return _Panel(
            f"[WARN] error leyendo outline: {oi.error}",
            title="outline", border_style="yellow",
        )
    if oi.source == "none":
        body = "[WARN] 0 capítulos detectados (sin outline ni heurística)"
    elif oi.source == "heuristic":
        body = f"[WARN] {oi.count} capítulos via heurística C8 (sin outline embebido)"
    else:
        body = f"[OK] {oi.count} capítulos desde outline embebido"
    lines: list[str] = [body]
    for level, title, page in oi.items[:_OUTLINE_ITEM_LIMIT]:
        indent = "  " * (level - 1)
        lines.append(f"{indent}- L{level}: {title} (p. {page})")
    if oi.count > len(oi.items):
        lines.append(f"[dim]  +{oi.count - len(oi.items)} más[/dim]")
    return _Panel("\n".join(lines), title="outline", border_style="cyan")


def _section_fonts(fi: FontsInspection) -> _Panel:
    if fi.error:
        return _Panel(
            f"[WARN] error enumerando fuentes: {fi.error}",
            title="fuentes", border_style="yellow",
        )
    if fi.count == 0:
        body = "[WARN] 0 fuentes distintas detectadas"
    else:
        body = f"[OK] {fi.count} fuentes distintas"
    lines: list[str] = [body]
    for name, ftype in fi.items:
        lines.append(f"  - {name} ({ftype})")
    return _Panel("\n".join(lines), title="fuentes", border_style="cyan")


def _section_headers(hi: HeadersInspection) -> _Panel:
    if hi.error:
        return _Panel(
            f"[WARN] error: {hi.error}",
            title="headers/footers", border_style="yellow",
        )
    if not hi.headers and not hi.footers:
        body = f"[OK] 0 headers/footers repetidos (threshold={hi.threshold})"
    else:
        body = (
            f"[WARN] {len(hi.headers)} header(s) repetido(s), "
            f"{len(hi.footers)} footer(s) repetido(s) (threshold={hi.threshold})"
        )
    lines: list[str] = [body]
    for h in hi.headers:
        lines.append(f"  header: {h!r}")
    for f in hi.footers:
        lines.append(f"  footer: {f!r}")
    return _Panel("\n".join(lines), title="headers/footers", border_style="cyan")


# Evita "imported but unused" si en el futuro alguien quiere re-exportar
# ``_check`` o similar; también mantiene un anchor para el linter.

