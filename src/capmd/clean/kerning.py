"""Colapsa runs de letras/dígitos uppercase separadas por 1-2 espacios.

PDFs con kerning visual exagerado producen líneas como::

    C H A P T E R   1 1

que ``markitdown`` extrae literalmente. Este cleaner las colapsa a
``CHAPTER 11``, preservando el whitespace entre grupos.

Scope: solo líneas que tras strip son 100% uppercase + dígitos +
espacios (sin puntuación ni minúsculas). False-positive guards:

- Listas como ``A B C`` (no son uppercase-puras si tienen punctuation
  o si están en un bloque con minúsculas).
- Headings ``Section A`` (contienen minúsculas).
- Prosa mixta ``Write your A B C clearly`` (contiene lowercase).
- Code fences ```` ``` ... ``` ```` (preservados por
  :func:`split_outside_fences`).
"""

from __future__ import annotations

import re

from capmd.clean._fences import split_outside_fences
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "DEFAULT_NAME",
    "KerningCleaner",
    "collapse_kerning",
]


DEFAULT_NAME = "kerning"

# Token individual: una letra uppercase o dígito seguido (opcional) por
# más tokens separados por 1-2 espacios. \b asegura boundary en cada
# extremo para no comerse sub-tokens de palabras reales.
_TOKEN_RE = re.compile(r"\b[A-Z0-9](?: {1,2}[A-Z0-9])+\b")

# Detección de línea "uppercase pura": solo letras uppercase, dígitos y
# espacios (con trim). Sin puntuación, sin minúsculas, sin underscores.
_UPPERCASE_LINE_RE = re.compile(r"^[A-Z0-9 ]+$")


def _collapse_match(m: re.Match) -> str:
    """Une los tokens del match eliminando los espacios entre ellos."""
    return m.group(0).replace(" ", "")


def _is_uppercase_only_line(line: str) -> bool:
    s = line.strip()
    return bool(s) and bool(_UPPERCASE_LINE_RE.match(s))


def collapse_kerning(text: str) -> str:
    """Versión pura ``str -> str`` del cleaner para tests.

    Colapsa runs de caracteres uppercase/dígitos separados por 1-2
    espacios en líneas que son 100% uppercase. El resto del texto se
    preserva intacto (incluyendo líneas mixtas, code fences y líneas
    con puntuación).
    """
    if not text:
        return text
    out_lines: list[str] = []
    for original_line in text.split("\n"):
        if _is_uppercase_only_line(original_line):
            out_lines.append(_TOKEN_RE.sub(_collapse_match, original_line))
        else:
            out_lines.append(original_line)
    return "\n".join(out_lines)


class KerningCleaner(Cleaner):
    """Cleaner que colapsa runs de letras/dígitos uppercase separadas
    por 1-2 espacios en líneas 100% uppercase.

    FIX-8 / D9: artefacto de markitdown / pypdfium2 con tipografía
    en kerning visual exagerado.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    @staticmethod
    def _apply(md: str, ctx: CleanContext) -> CleanResult:
        if not md:
            return CleanResult(text=md, changes=0)

        # split_outside_fences protege code blocks ``` ... ``` y
        # bloques indentados de 4+ espacios.
        segments = split_outside_fences(md)
        new_segments: list[str] = []
        total_changes = 0
        for segment, in_fence in segments:
            if in_fence:
                new_segments.append(segment)
                continue
            new_segment = collapse_kerning(segment)
            if new_segment != segment:
                # Contar el número de matches colapsados como proxy
                # de changes (suficiente para capmd.json sin inventar
                # métricas complejas).
                total_changes += sum(
                    1 for _ in _TOKEN_RE.finditer(segment)
                )
            new_segments.append(new_segment)
        return CleanResult(
            text="".join(new_segments),
            changes=total_changes,
        )
