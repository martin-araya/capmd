"""Heurística de detección de capítulos en PDFs sin outline (fase C8).

Estrategia en cascada:
  1. Patrones de texto en las primeras líneas de cada página
     (``Chapter N``, ``Capítulo N``, ``N. Title``).
  2. Si los patrones no encuentran al menos 2 candidatos, heurística
     de tamaño de fuente vía ``pypdfium2``: páginas cuyo font máximo
     supera 1.5x la mediana del documento.
  3. Si nada produce resultados, ``ChapterDetectionFailed``.

Limitaciones (documentadas):
  - No detecta sub-entradas (nivel 2+).
  - No hace OCR: si el PDF es escaneado, falla limpio con la sugerencia
    de ``--pages``.
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

from pypdf import PdfReader
from pypdfium2 import PdfDocument

from capmd.errors import ChapterDetectionFailed
from capmd.models import Chapter

__all__ = ["detect_chapters"]

_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*Chapter\s+\d+\b.*", re.IGNORECASE),
    re.compile(r"^\s*Cap[ií]tulo\s+\d+\b.*", re.IGNORECASE),
    re.compile(r"^\s*\d+\.\s+[A-Z].*"),
)

_HEAD_FRAGMENT_CHARS = 200
_FONT_THRESHOLD_MULTIPLIER = 1.5
_MIN_TEXT_CANDIDATES_FOR_FONT_FALLBACK = 2


def _scan_text_patterns(path: Path) -> list[tuple[int, str]]:
    """Devuelve ``[(page_num, title), ...]`` para páginas que matchean un patrón.

    Solo se inspeccionan los primeros ``_HEAD_FRAGMENT_CHARS`` caracteres
    de cada página para reducir falsos positivos del cuerpo.
    """
    reader = PdfReader(str(path))
    found: list[tuple[int, str]] = []
    for page_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        head = text[:_HEAD_FRAGMENT_CHARS]
        first_line = next((ln for ln in head.splitlines() if ln.strip()), "")
        if not first_line:
            continue
        for pattern in _TEXT_PATTERNS:
            if pattern.match(first_line):
                found.append((page_idx, first_line.strip()))
                break
    return found


def _all_font_sizes(path: Path) -> list[float]:
    """Devuelve todos los font sizes del documento (excluyendo 0/None)."""
    pdf = PdfDocument(str(path))
    sizes: list[float] = []
    for page in pdf:
        textpage = page.get_textpage()
        for i in range(textpage.count_chars()):
            obj = textpage.get_textobj(i)
            if obj is None:
                continue
            try:
                size = obj.get_font_size()
            except Exception:  # pragma: no cover
                continue  # pragma: no cover
            if size and size > 0:  # pragma: no cover
                sizes.append(size)
    return sizes


def _max_font_per_page(path: Path) -> list[float]:
    """Devuelve el font máximo por página (0 si la página no tiene texto)."""
    pdf = PdfDocument(str(path))
    maxima: list[float] = []
    for page in pdf:
        textpage = page.get_textpage()
        sizes: list[float] = []
        for i in range(textpage.count_chars()):
            obj = textpage.get_textobj(i)
            if obj is None:
                continue
            try:
                size = obj.get_font_size()
            except Exception:  # pragma: no cover
                continue  # pragma: no cover
            if size and size > 0:  # pragma: no cover
                sizes.append(size)
        maxima.append(max(sizes) if sizes else 0.0)
    return maxima


def _largest_text_on_page(path: Path, page_num: int) -> str:
    """Devuelve el run de texto contiguo con font máximo en ``page_num`` (1-indexed)."""
    pdf = PdfDocument(str(path))
    page = pdf[page_num - 1]
    textpage = page.get_textpage()
    text = textpage.get_text_range() or ""

    sizes: list[float] = []
    for i in range(textpage.count_chars()):
        obj = textpage.get_textobj(i)
        if obj is None:
            continue
        try:
            sizes.append(obj.get_font_size())
        except Exception:  # pragma: no cover
            sizes.append(0.0)  # pragma: no cover

    if not sizes or not text:
        return f"Chapter {page_num}"  # pragma: no cover

    # Encontrar el primer run contiguo con el font máximo.
    max_size = max(s for s in sizes if s > 0)
    start = next((i for i, s in enumerate(sizes) if s == max_size), 0)
    end = start
    while end < len(sizes) and sizes[end] == max_size:
        end += 1
    return text[start:end].strip() or f"Chapter {page_num}"


def _scan_font_size(path: Path) -> list[tuple[int, str]]:
    """Heurística de font-size: devuelve ``[(page_num, title), ...]``.

    Compara el font máximo de cada página contra la mediana GLOBAL
    de todos los font sizes del documento (no contra max-per-page, que
    sería 18 en cada página de un libro con headings uniformes).
    """
    max_per_page = _max_font_per_page(path)
    if not any(max_per_page):
        return []
    all_sizes = _all_font_sizes(path)
    if not all_sizes:
        return []  # pragma: no cover
    median = statistics.median(all_sizes)
    threshold = median * _FONT_THRESHOLD_MULTIPLIER
    found: list[tuple[int, str]] = []
    for idx, size in enumerate(max_per_page, start=1):
        if size >= threshold:
            title = _largest_text_on_page(path, idx)
            found.append((idx, title or f"Chapter {idx}"))
    return found


def detect_chapters(path: Path) -> list[Chapter]:
    """Detecta capítulos en un PDF sin outline y devuelve ``list[Chapter]``.

    Cada :class:`Chapter` tiene ``level=1``, ``start_page`` 1-indexed,
    ``end_page=start_page`` (provisional) e ``index`` 1..N. Aplicar
    :func:`capmd.sources.pdf.infer_ranges` para poblar ``end_page``.

    Levanta :class:`ChapterDetectionFailed` si ninguna estrategia
    produce resultados (PDF escaneado, sin headings, etc.). El mensaje
    sugiere ``--pages`` como salida manual.
    """
    text_candidates = _scan_text_patterns(path)

    candidates = text_candidates
    if len(text_candidates) < _MIN_TEXT_CANDIDATES_FOR_FONT_FALLBACK:
        font_candidates = _scan_font_size(path)
        if len(font_candidates) > len(text_candidates):
            candidates = font_candidates

    if not candidates:
        raise ChapterDetectionFailed(
            "no se detectaron capítulos por texto ni por tamaño de fuente",
            hint="el PDF puede ser un escaneo; usá --pages para recortar manualmente",
        )

    return [
        Chapter(
            title=title,
            level=1,
            start_page=page_num,
            end_page=page_num,
            index=i,
        )
        for i, (page_num, title) in enumerate(candidates, start=1)
    ]
