"""Centinelas de página para el markdown convertido.

D5 del roadmap. Las funciones aquí son puras y se usan desde
``Engine.convert_pages`` (D5) y desde :class:`HeaderFooterCleaner` (D4).
"""

from __future__ import annotations

import re

__all__ = [
    "PAGE_MARKER_RE",
    "PAGE_MARKER_TEMPLATE",
    "insert_page_markers",
    "join_pages",
    "split_by_page_markers",
    "strip_page_markers",
]

PAGE_MARKER_TEMPLATE = "<!-- page {n} -->"
PAGE_MARKER_RE = re.compile(r"<!-- page (\d+) -->")
_PAGE_MARKER_SPLIT_RE = re.compile(r"<!-- page \d+ -->")


def insert_page_markers(
    pages: list[str],
    *,
    template: str = PAGE_MARKER_TEMPLATE,
) -> str:
    """Une ``pages`` insertando un centinela por página entre cada par.

    El resultado siempre contiene exactamente ``len(pages) - 1`` markers:
    ``[page_1][MARKER 2][page_2][MARKER 3]...[MARKER N][page_N]``.
    """
    if not pages:
        return ""
    parts: list[str] = [pages[0]]
    for i, page in enumerate(pages[1:], start=2):
        parts.append(template.format(n=i))
        parts.append(page)
    return "\n".join(parts)


def split_by_page_markers(text: str) -> list[str]:
    """Parte ``text`` por los centinelas de página.

    Devuelve una lista con ``N + 1`` elementos donde ``N`` es la cantidad
    de markers: ``[contenido_antes_marker_1, contenido_entre_1_y_2, ...]``.

    ``\\n`` adyacentes a cada marker se descartan (son separadores entre
    páginas). Los ``\\n`` internos de cada página se preservan.

    Si el texto empieza con un marker, el primer elemento es la cadena
    vacía. Si no contiene markers, devuelve ``[text]``.
    """
    if not text:
        return [""]
    return [p.strip("\n") for p in _PAGE_MARKER_SPLIT_RE.split(text)]


def strip_page_markers(text: str) -> str:
    """Elimina los centinelas de página. El resto del texto queda intacto."""
    if not text:
        return text
    return PAGE_MARKER_RE.sub("", text)


def join_pages(pages: list[str]) -> str:
    """Une páginas con saltos de línea, sin centinelas."""
    return "\n".join(pages)
