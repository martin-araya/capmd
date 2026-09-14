"""Single H1 enforcement (D8).

Garantiza a lo sumo un ``#`` (H1) en el documento: el primero se
mantiene, cualquier H1 adicional se degrada a ``##`` (H2).

Code fences ````` y ``~~~`` se respetan: las líneas dentro no se
tocan aunque parezcan headings.
"""

from __future__ import annotations

import re

from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "DEFAULT_NAME",
    "HEADING_RE",
    "SingleH1Cleaner",
    "count_atx_level",
    "enforce_single_h1",
]

DEFAULT_NAME = "single_h1"

HEADING_RE = re.compile(r"^(#{1,6})(?:\s|$)")


def count_atx_level(line: str) -> int:
    """Devuelve el nivel 1-6 si ``line`` es ATX heading, 0 si no."""
    m = HEADING_RE.match(line)
    if m is None:
        return 0
    return min(len(m.group(1)), 6)


def enforce_single_h1(text: str) -> str:
    """Demota los H1 extras a H2; respeta code fences ```` ``` ```` y ``~~~``."""
    if not text:
        return text
    out: list[str] = []
    seen_h1 = False
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if count_atx_level(line) == 1:
            if seen_h1:
                out.append("##" + line[1:])
            else:
                seen_h1 = True
                out.append(line)
        else:
            out.append(line)
    return "\n".join(out)


class SingleH1Cleaner(Cleaner):
    """Cleaner que degrada H1s extras a H2."""

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
        before_h1 = sum(1 for line in md.splitlines() if count_atx_level(line) == 1)
        if before_h1 <= 1:
            return CleanResult(text=md, changes=0)
        out = enforce_single_h1(md)
        return CleanResult(text=out, changes=before_h1 - 1)
