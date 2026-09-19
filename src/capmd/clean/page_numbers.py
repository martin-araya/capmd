"""Eliminación de líneas que son números de página (D6).

Patrones reconocidos (en orden):

1. ``47`` — número solo en la línea.
2. ``— 47 —`` / ``– 47 –`` / ``- 47 -`` — em/en-dash o hyphen + número + cierre.
3. ``47 | Capítulo 3`` — número + pipe + texto.
4. ``Capítulo 3 | 47`` — texto + pipe + número (variante invertida).
5. ``204  PART II  Requirements development`` (FIX-7 / D8) — footer
   editorial de libros académicos con page number + 2+ espacios +
   keyword cerrada (PART/Chapter/Section/APPENDIX/Volume/Module/Unit) +
   texto.

NO elimina:

- Listas numeradas: ``1. foo`` (termina en ``.``), ``2) bar`` (termina en ``)``).
- Referencias inline: ``ver página 47`` (no es línea completa).
- Horizontal rule: ``---`` (sin número).
- Inline: ``204 is the answer`` (palabra lowercase tras los espacios
  no está en la alternancia cerrada del regex editorial — FIX-7
  false-positive guard explícito).
"""

from __future__ import annotations

import re

from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "DEFAULT_NAME",
    "EDITORIAL_FOOTER_RE",
    "EMDASH_NUMBER_RE",
    "NUMBER_ONLY_RE",
    "PIPE_NUMBER_LEFT_RE",
    "PIPE_NUMBER_RIGHT_RE",
    "PageNumberCleaner",
    "is_page_number_line",
    "strip_page_number_lines",
]

DEFAULT_NAME = "page_numbers"

NUMBER_ONLY_RE = re.compile(r"^\d+$")
EMDASH_NUMBER_RE = re.compile(r"^[—–\-]\s*\d+\s*[—–\-]$")
PIPE_NUMBER_LEFT_RE = re.compile(r"^\d+\s*\|.+$")
PIPE_NUMBER_RIGHT_RE = re.compile(r"^.+\|\s*\d+$")
# Footer editorial: "<página>  <KEYWORD>  <texto>". Los keywords
# son case-sensitive y lexicamente cerrados para no romper el caso
# negativo "204 is the answer" (la palabra "is" no está en la
# alternancia). Sin IGNORECASE justamente para mantener el guard.
EDITORIAL_FOOTER_RE = re.compile(
    r"^\s*\d{1,4}\s{2,}(?:PART|Chapter|Section|APPENDIX|Volume|Module|Unit)\s+\S.*$"
)


def is_page_number_line(line: str) -> bool:
    """True si ``line`` (sin newline) es una línea de número de página."""
    if not line or not line.strip():
        return False
    return (
        NUMBER_ONLY_RE.match(line) is not None
        or EMDASH_NUMBER_RE.match(line) is not None
        or PIPE_NUMBER_LEFT_RE.match(line) is not None
        or PIPE_NUMBER_RIGHT_RE.match(line) is not None
        or EDITORIAL_FOOTER_RE.match(line) is not None
    )


def strip_page_number_lines(text: str) -> str:
    """Devuelve ``text`` con las líneas de números de página eliminadas.

    Preserva los ``\\n`` originales; una línea eliminada deja su
    ``\\n`` en el output como separador vacío.
    """
    if not text:
        return text
    out: list[str] = []
    current: list[str] = []
    for char in text:
        if char == "\n":
            line = "".join(current)
            if not is_page_number_line(line):
                out.append(line)
            current = []
            out.append("\n")
        else:
            current.append(char)
    line = "".join(current)
    if line and not is_page_number_line(line):
        out.append(line)
    return "".join(out)


class PageNumberCleaner(Cleaner):
    """Cleaner que elimina líneas de números de página sueltos."""

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
        before_count = sum(1 for line in md.splitlines() if is_page_number_line(line))
        out = strip_page_number_lines(md)
        return CleanResult(text=out, changes=before_count)
