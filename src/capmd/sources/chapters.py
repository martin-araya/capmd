"""Lookup de capítulos por índice o por substring (fase C5) y
parser de ``--chapters`` para ``capmd batch`` (H2).

Resuelve la spec de ``--chapter`` contra la lista de capítulos
proveniente de :func:`capmd.sources.pdf.read_outline` (post
:func:`capmd.sources.pdf.infer_ranges` para tener ``end_page`` resuelto).
"""

from __future__ import annotations

from capmd.models import Chapter

__all__ = ["parse_chapters_spec", "resolve_chapter"]


def parse_chapters_spec(spec: str, total: int) -> tuple[int, ...]:
    """Parsea ``--chapters`` devolviendo índices ordenados y únicos.

    Sintaxis (mismo DSL que ``--pages``):
      - ``"1"``        -> ``(1,)``
      - ``"1-12"``     -> ``(1, 2, ..., 12)``
      - ``"1,3,5"``    -> ``(1, 3, 5)``
      - ``"1-3,7,10-12"`` -> ``(1, 2, 3, 7, 10, 11, 12)``

    Errores (todos ``ValueError``; el CLI los mapea a exit 2):

      - Spec vacío.
      - Tokens no numéricos (``"abc"``, ``"1.5"``).
      - Lados abiertos (``"1-"``, ``"-1"``, ``"-"``).
      - Rango descendente (``"5-3"``).
      - Cualquier índice fuera de ``[1, total]`` (``total <= 0``
        reporta ``"PDF sin outline"`` antes de parsear).

    Importante: ``batch`` solo acepta índices enteros. Para resolver
    por nombre/título está el flag singular ``--chapter`` de
    :func:`resolve_chapter`.
    """
    if total < 1:
        raise ValueError(
            "el PDF no tiene outline (o no se pudo leer); "
            "capmd batch requiere --chapters por índice, "
            "usá --pages para especificar el rango a mano"
        )
    if not spec or not spec.strip():
        raise ValueError("--chapters vacío")

    tokens = [tok.strip() for tok in spec.split(",") if tok.strip()]
    if not tokens:
        raise ValueError(f"--chapters {spec!r}: ningún token válido")

    out: list[int] = []
    for tok in tokens:
        # Lados abiertos explícitos.
        if tok.startswith("-") or tok.endswith("-"):
            # Soporte del patrón "1-" rechazado de manera clara.
            raise ValueError(
                f"--chapters {spec!r}: rango abierto en {tok!r} "
                f"(batch solo acepta rangos cerrados A-B)"
            )
        if "-" in tok:
            try:
                a_str, b_str = tok.split("-", 1)
                a, b = int(a_str), int(b_str)
            except ValueError as exc:
                raise ValueError(
                    f"--chapters {spec!r}: token no numérico en {tok!r}"
                ) from exc
            if a < 1 or b < 1:
                raise ValueError(
                    f"--chapters {spec!r}: los índices son 1-indexed; "
                    f"{tok!r} tiene un lado < 1"
                )
            if b < a:
                raise ValueError(
                    f"--chapters {spec!r}: rango descendente en {tok!r}"
                )
            if a > total or b > total:
                raise ValueError(
                    f"--chapters {spec!r}: índice fuera de rango "
                    f"(outline tiene {total}); {tok!r}"
                )
            out.extend(range(a, b + 1))
        else:
            try:
                n = int(tok)
            except ValueError as exc:
                raise ValueError(
                    f"--chapters {spec!r}: token no numérico en {tok!r}"
                ) from exc
            if n < 1:
                raise ValueError(
                    f"--chapters {spec!r}: los índices son 1-indexed; {tok!r} no es válido"
                )
            if n > total:
                raise ValueError(
                    f"--chapters {spec!r}: índice {n} fuera de rango "
                    f"(outline tiene {total})"
                )
            out.append(n)

    return tuple(sorted(set(out)))


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
        raise ValueError("el PDF no tiene outline; usá --pages para especificar el rango")

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
