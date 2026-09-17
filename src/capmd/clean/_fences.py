"""Detección y segmentación de code fences.

Usado por D10 para preservar el contenido de ```` ``` ```` y ``~~~``
cuando los cleaners de whitespace o de-hyphenation corren.

Markdown spec:
- Fence open: 3+ backticks o 3+ tildes al inicio de línea (con 0-3
  espacios de indentación permitidos).
- Fence close: misma cantidad (o más) del mismo carácter.
- Solo ``` cierra ``` y solo ~~~ cierra ~~~.
- Un fence no cerrado deja todo el resto del documento "dentro".
"""

from __future__ import annotations

import re
from collections.abc import Callable

__all__ = [
    "FENCE_LINE_RE",
    "apply_outside_fences",
    "split_outside_fences",
]

FENCE_LINE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")


def _is_fence_line(line: str) -> tuple[str, str] | None:
    """Devuelve ``(marker_char, marker_full)`` si ``line`` es un fence, else None."""
    m = FENCE_LINE_RE.match(line.lstrip())
    if m is None:
        return None
    marker = m.group(2)
    return marker[0], marker


def split_outside_fences(text: str) -> list[tuple[str, bool]]:
    """Segmenta ``text`` en ``(segment, in_fence)``.

    Cada segmento es texto contiguo (puede incluir ``\\n``).
    ``in_fence=True`` indica que el segmento está dentro de un fence.
    Un fence no cerrado deja todo el resto como ``in_fence=True``.
    """
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    segments: list[tuple[str, bool]] = []
    buffer: list[str] = []
    in_fence = False
    fence_char: str | None = None

    def flush() -> None:
        nonlocal buffer, in_fence
        if buffer:
            segments.append(("".join(buffer), in_fence))
            buffer = []

    for line in lines:
        hit = _is_fence_line(line)
        if hit is not None:
            char, _marker = hit
            if in_fence:
                if char == fence_char:
                    buffer.append(line)
                    flush()
                    in_fence = False
                    fence_char = None
                    continue
                buffer.append(line)  # pragma: no cover
                continue  # pragma: no cover
            flush()
            buffer.append(line)
            in_fence = True
            fence_char = char
            continue
        buffer.append(line)

    flush()
    return segments


def apply_outside_fences(text: str, fn: Callable[[str], str]) -> str:
    """Aplica ``fn`` solo a segmentos fuera de fences; preserva intactos
    los segmentos dentro.
    """
    if not text:
        return text
    segments = split_outside_fences(text)
    out: list[str] = []
    for seg, in_fence in segments:
        if in_fence:
            out.append(seg)
        else:
            out.append(fn(seg))
    return "".join(out)
