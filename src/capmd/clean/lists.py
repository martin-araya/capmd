"""Reparación de listas markdown (D11).

Dos reparaciones:

1. **Bullet markers rotos:** ``•``, ``‣``, ``–``, ``◦``, ``▪``, ``·`` al
   inicio de línea se normalizan a ``-``. ``*`` y ``+`` ya son
   válidos y se preservan.

2. **Listas numeradas partidas:** secuencias de items numerados
   (``^\\d+[.)]\\s+\\S``) separadas solo por líneas en blanco se
   re-mergean en una lista contigua.

Las reparaciones se aplican fuera de fences (mismo patrón que D10).
"""

from __future__ import annotations

import re

from capmd.clean._fences import split_outside_fences
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "BROKEN_BULLETS_MAP",
    "DEFAULT_NAME",
    "NUMBERED_ITEM_RE",
    "ListsCleaner",
    "repair_bullets",
    "repair_lists",
    "repair_numbered_lists",
]

DEFAULT_NAME = "lists"

BROKEN_BULLETS_MAP: dict[str, str] = {
    "•": "-",  # U+2022 BULLET
    "‣": "-",  # U+2023 TRIANGULAR BULLET
    "–": "-",  # U+2013 EN DASH
    "◦": "-",  # U+25E6 WHITE BULLET
    "▪": "-",  # U+25AA BLACK SMALL SQUARE
    "·": "-",  # U+00B7 MIDDLE DOT
}

NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+[.)])\s+\S")

_BULLET_RE = re.compile(r"^(\s*)([" + "".join(BROKEN_BULLETS_MAP.keys()) + r"])(\s+)")
_BLANK_LINE_RE = re.compile(r"^\s*$")


def repair_bullets(text: str) -> str:
    """Reemplaza bullet markers rotos al inicio de línea por ``-``.

    Solo aplica cuando el bullet roto está seguido de whitespace
    (es un bullet real, no un carácter en medio de prosa).

    Respeta fences ```` ``` ```` y ``~~~``: dentro de fences no se toca.
    """
    if not text:
        return text

    def _fix_line(line: str) -> str:
        m = _BULLET_RE.match(line)
        if m is None:
            return line
        if m.group(3):
            return f"{m.group(1)}- {line[m.end() :]}"
        return f"{m.group(1)}-"  # pragma: no cover

    segments = split_outside_fences(text)
    out: list[str] = []
    for seg, in_fence in segments:
        if in_fence:
            out.append(seg)
            continue
        lines = seg.splitlines(keepends=True)
        out.append("".join(_fix_line(line) for line in lines))
    return "".join(out)


def _is_numbered_item(line: str) -> bool:
    return NUMBERED_ITEM_RE.match(line) is not None


def _is_blank(line: str) -> bool:
    return _BLANK_LINE_RE.match(line) is not None


def _process_page_numbered(page: str) -> str:
    """Procesa una página (sin fences) para mergear listas numeradas partidas."""
    lines = page.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        if _is_numbered_item(lines[i]):
            items_idx: list[int] = []
            j = i
            while j < len(lines):
                if _is_numbered_item(lines[j]):
                    items_idx.append(j)
                    j += 1
                elif _is_blank(lines[j]):
                    k = j + 1
                    while k < len(lines) and _is_blank(lines[k]):
                        k += 1
                    if k < len(lines) and _is_numbered_item(lines[k]):
                        j = k
                    else:
                        break
                else:
                    break
            if len(items_idx) >= 2:
                out.extend(lines[idx] for idx in items_idx)
            else:
                out.extend(lines[i:j])
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "".join(out)


def repair_numbered_lists(text: str) -> str:
    """Mergear secuencias de items numerados separadas por blancos."""
    if not text:
        return text
    segments = split_outside_fences(text)
    out: list[str] = []
    for seg, in_fence in segments:
        if in_fence:
            out.append(seg)
        else:
            out.append(_process_page_numbered(seg))
    return "".join(out)


def repair_lists(text: str) -> str:
    """Aplica ambas reparaciones en orden: bullets primero, luego números."""
    return repair_numbered_lists(repair_bullets(text))


class ListsCleaner(Cleaner):
    """Cleaner que repara bullet markers y mergea listas numeradas partidas."""

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

        bullets_out = repair_bullets(md)
        n_bullets_fixed = _count_bullet_changes(md, bullets_out)

        numbered_out = repair_numbered_lists(bullets_out)
        n_blocks_merged = _count_block_merges(bullets_out, numbered_out)

        return CleanResult(
            text=numbered_out,
            changes=n_bullets_fixed + n_blocks_merged,
        )


def _count_bullet_changes(before: str, after: str) -> int:
    if before == after:
        return 0
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    if len(before_lines) != len(after_lines):
        return max(0, len(after_lines) - len(before_lines))  # pragma: no cover
    return sum(1 for a, b in zip(before_lines, after_lines, strict=False) if a != b)


def _count_block_merges(before: str, after: str) -> int:
    """Cuenta cuántas secuencias de blank-lines-between-numbered-items se eliminaron."""
    if before == after:
        return 0
    before_segs = split_outside_fences(before)
    after_segs = split_outside_fences(after)
    if len(before_segs) != len(after_segs):
        return 0  # pragma: no cover
    total = 0
    for (b, b_in), (a, a_in) in zip(before_segs, after_segs, strict=False):
        if b_in != a_in:
            continue  # pragma: no cover
        before_blank_count = sum(1 for ln in b.splitlines() if _is_blank(ln))
        after_blank_count = sum(1 for ln in a.splitlines() if _is_blank(ln))
        total += max(0, before_blank_count - after_blank_count)
    return total
