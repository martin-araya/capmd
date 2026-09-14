"""Cortes de párrafo (D14).

Une líneas rotas por ancho de columna o salto de página que forman un
mismo párrafo, sin unir párrafos distintos.

Heurística principal (per roadmap):
- La línea anterior no termina en ``.``, ``:`` o ``;``
- La línea siguiente empieza en minúscula

Extensiones (decisiones D14):
- Opening brackets (``(``, ``[``, ``"``) al final de la línea anterior
  fuerzan join con la siguiente.
- Líneas que son heading, list item, blockquote o fence delimiter NO
  inician un buffer (cada uno es su propio bloque).
- Code fences ya están excluidas por ``split_outside_fences``.
"""

from __future__ import annotations

import re

from capmd.clean._fences import split_outside_fences
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "DEFAULT_NAME",
    "OPENING_BRACKETS",
    "TERMINAL_PUNCTUATION",
    "ParagraphJoinsCleaner",
    "is_skip_line",
    "join_paragraphs",
    "should_join",
]

DEFAULT_NAME = "paragraph_joins"

TERMINAL_PUNCTUATION = ".:;"
OPENING_BRACKETS = '(["'

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_FENCE_DELIM_RE = re.compile(r"^(\s*)(`{3,}|~{3,})")


def _ends_with_terminal(s: str) -> bool:
    return bool(s) and s[-1] in TERMINAL_PUNCTUATION


def is_skip_line(line: str) -> bool:
    """True si la línea es heading, list item, blockquote o fence delimiter."""
    stripped = line.lstrip()
    if not stripped:
        return False
    if _HEADING_RE.match(stripped):
        return True
    if _LIST_ITEM_RE.match(stripped):
        return True
    if _BLOCKQUOTE_RE.match(stripped):
        return True
    return bool(_FENCE_DELIM_RE.match(stripped))


def should_join(prev: str, curr: str) -> bool:
    """True si ``curr`` continúa el párrafo de ``prev``."""
    prev_stripped = prev.rstrip("\n").rstrip()
    curr_stripped = curr.lstrip("\n").lstrip()
    if not curr_stripped:
        return False
    if is_skip_line(curr):
        return False
    first_char = curr_stripped[0]
    if first_char.isupper():
        return False
    if first_char in OPENING_BRACKETS and not _ends_with_terminal(prev_stripped):
        return True
    if _ends_with_terminal(prev_stripped):
        return False
    if prev_stripped and prev_stripped[-1] in OPENING_BRACKETS:
        return True
    return True


def _merge(prev: str, curr: str) -> str:
    p = prev.rstrip("\n").rstrip()
    c = curr.lstrip("\n").lstrip()
    collapsed = " ".join(p.split())
    return collapsed + " " + c + "\n"


def join_paragraphs(text: str) -> str:
    """Une líneas rotas por ancho de columna que forman un mismo párrafo."""
    if not text:
        return text
    segments = split_outside_fences(text)
    out_parts: list[str] = []
    for seg, in_fence in segments:
        if in_fence:
            out_parts.append(seg)
            continue
        out_parts.append(_join_segment(seg))
    return "".join(out_parts)


def _join_segment(segment: str) -> str:
    lines = segment.splitlines(keepends=True)
    out: list[str] = []
    buffer: str | None = None
    for line in lines:
        if buffer is not None:
            if should_join(buffer, line):
                buffer = _merge(buffer, line)
                continue
            out.append(buffer)
            buffer = None
        if is_skip_line(line):
            out.append(line)
            continue
        if not line.strip():
            out.append(line)
            continue
        buffer = line
    if buffer is not None:
        out.append(buffer)
    return "".join(out)


class ParagraphJoinsCleaner(Cleaner):
    """Une líneas que forman un mismo párrafo."""

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    def _apply(self, md: str, ctx: CleanContext) -> CleanResult:
        if not md:
            return CleanResult(text=md, changes=0)
        before_lines = sum(1 for line in md.splitlines() if line.strip())
        out = join_paragraphs(md)
        after_lines = sum(1 for line in out.splitlines() if line.strip())
        if out == md:
            return CleanResult(text=md, changes=0)
        n_joins = max(0, before_lines - after_lines)
        return CleanResult(text=out, changes=n_joins)
