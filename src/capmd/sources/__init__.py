"""Lectura de documentos por formato.

Cada formato (PDF, EPUB, DOCX…) expone una :class:`Source` con la
información que las fases siguientes necesitan: outline/TOC, número de
páginas, recorte. Las fases C1-C9 implementan PDF y EPUB.

El lector de EPUB vive en :mod:`capmd.sources.epub` y se importa
explícitamente (``from capmd.sources.epub import read_outline``)
para evitar el choque con el ``read_outline`` de PDF. El dispatcher
del CLI elige uno u otro según la extensión del archivo.
"""

from capmd.sources.chapters import parse_chapters_spec, resolve_chapter
from capmd.sources.epub import slice_epub
from capmd.sources.heuristic import detect_chapters
from capmd.sources.pages import parse_pages, translate_spec
from capmd.sources.pdf import (
    OutlineEntry,
    infer_ranges,
    read_outline,
    read_outline_tuples,
    read_outline_with_fallback,
    slice_pdf,
)

__all__ = [
    "OutlineEntry",
    "detect_chapters",
    "infer_ranges",
    "parse_chapters_spec",
    "parse_pages",
    "read_outline",
    "read_outline_tuples",
    "read_outline_with_fallback",
    "resolve_chapter",
    "slice_epub",
    "slice_pdf",
    "translate_spec",
]
