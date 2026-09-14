"""Lookup de capítulos por índice o por substring (fase C5).

Resuelve la spec de ``--chapter`` contra la lista de capítulos
proveniente de :func:`capmd.sources.pdf.read_outline` (post
:func:`capmd.sources.pdf.infer_ranges` para tener ``end_page`` resuelto).
"""

from __future__ import annotations

from capmd.models import Chapter

__all__ = ["resolve_chapter"]


def resolve_chapter(chapters: list[Chapter], spec: str) -> Chapter:
    """Devuelve el :class:`Chapter` que matchea ``spec``.

    Reglas:
      - Si ``spec`` parsea como entero positivo: match por
        ``chapter.index == spec`` (incluye sub-entradas: el índice es
        la posición DFS en el outline completo).
      - En caso contrario: match por substring case-insensitive del
        título (``spec.lower() in chapter.title.lower()``).

    Errores (todos ``ValueError``; el CLI los mapea a
    ``typer.BadParameter``, exit 2):
      - Lista vacía, ``spec`` vacío, índice fuera de rango, 0 matches
        por substring, >1 match (ambigüedad).
    """
    if not spec or not spec.strip():
        raise ValueError("--chapter vacío")
    spec = spec.strip()

    if not chapters:
        raise ValueError(
            "el PDF no tiene outline; usá --pages para especificar el rango"
        )

    idx = _try_int(spec)
    if idx is not None:
        for ch in chapters:
            if ch.index == idx:
                return ch
        raise ValueError(
            f"no existe el índice {idx} en el TOC (hay {len(chapters)} entradas); "
            f"usá --chapter 'título' para buscar por nombre"
        )

    needle = spec.lower()
    matches = [ch for ch in chapters if needle in ch.title.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        titles = ", ".join(repr(ch.title) for ch in chapters)
        raise ValueError(f"ningún capítulo matchea {spec!r}; opciones: {titles}")
    listed = "\n".join(f"  {ch.index}. {ch.title!r}" for ch in matches)
    raise ValueError(f"{spec!r} es ambiguo; candidatos:\n{listed}")


def _try_int(s: str) -> int | None:
    """Devuelve ``int(s)`` si es un entero positivo, si no ``None``."""
    try:
        n = int(s)
    except ValueError:
        return None
    if n < 1:
        return None
    return n
