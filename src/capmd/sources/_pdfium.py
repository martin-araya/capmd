"""Helpers livianos sobre pypdfium2 (BUGS.md LOW #10).

El problema: ``PdfTextPage`` es un recurso nativo de PDFium que NO se
cierra automáticamente cuando sale de scope (Python garbage collector).
Para PDFs de 5000 páginas eso son 5000 ``PdfTextPage`` vivos hasta el
GC, con presión de memoria proporcional al tamaño del PDF.

Mitigación: helper :func:`with_textpage` que encapsula
``try/finally: tp.close()`` en un solo lugar. Los call sites obtienen
el textpage via callback en vez de manejar el ciclo de vida a mano.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import pypdfium2 as pdfium

from capmd.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def with_textpage(
    page: pdfium.PdfPage,
    fn: Callable[[pdfium.PdfTextPage], T],
) -> T | None:
    """Abre un ``PdfTextPage`` sobre ``page``, ejecuta ``fn(tp)``, y cierra.

    Garantiza que ``tp.close()`` se invoque incluso si ``fn`` levanta
    una excepción. Si ``page.get_textpage()`` falla, devuelve ``None``
    y loggea debug (defensivo, igual que el patrón actual en heuristic/
    inspect); el caller decide qué hacer con el resultado faltante.

    BUGS.md LOW #10: el código previo dejaba el ``PdfTextPage`` vivo
    hasta el GC. Para PDFs grandes esto multiplicaba la memoria por
    la cantidad de páginas.
    """
    try:
        tp = page.get_textpage()
    except (pdfium.PdfiumError, AttributeError, OSError) as exc:
        logger.debug("with_textpage: get_textpage failed: %s", exc)
        return None
    try:
        return fn(tp)
    finally:
        try:
            tp.close()
        except (pdfium.PdfiumError, AttributeError, OSError) as exc:  # pragma: no cover - defensivo
            logger.debug("with_textpage: tp.close() failed: %s", exc)
