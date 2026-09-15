"""Detección de captions de figuras en markdown (fase E5).

Un *caption* es una línea de texto que sigue el patrón
``Figura N.N — <descripción>`` (o variantes multi-idioma) y se asocia a
la figura más cercana arriba. Se usa como alt text del anchor ``![]()``
y se reinserta en cursiva ``*Figura N.N — <descripción>*`` debajo del
anchor.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["CAPTION_RE", "CaptionMatch", "find_caption_in_window", "italicize_caption"]

# Multi-idioma: ``Figura`` / ``Figure`` / ``Fig.`` / ``Fig``, seguidas de
# ``N.M`` y un separador (em-dash, hyphen o colon) y la descripción hasta
# fin de línea. Flag IGNORECASE para tolerar variantes de capitalización.
CAPTION_RE = re.compile(
    r"^(?P<prefix>Figura|Figure|Fig\.?)\s+"
    r"(?P<chapter>\d+)\.(?P<figure>\d+)\s*"
    r"(?P<sep>[—\-:])\s*"
    r"(?P<desc>.+?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CaptionMatch:
    """Caption detectado y su metadata posicional dentro de un bloque."""

    raw: str  # línea original completa, ej: "Figura 3.1 — Red square"
    chapter: int  # 3
    figure: int  # 1
    ref: str  # "3.1"
    description: str  # "Red square"
    line_index: int  # índice en la lista de líneas donde se encontró


def find_caption_in_window(
    lines: Sequence[str],
    start_idx: int,
    *,
    window: int = 3,
) -> CaptionMatch | None:
    """Busca un caption en las próximas ``window`` líneas no-vacías.

    Examina ``lines[start_idx + 1]`` en adelante. Las blank lines no
    cuentan para el límite de ``window`` (solo se cuentan las líneas
    con texto). Retorna el primer :class:`CaptionMatch` o ``None``.

    Usar ``window=0`` desactiva el lookup (retorna ``None`` siempre).
    """
    if window <= 0:
        return None

    seen_lines = 0
    offset = 0
    n = len(lines)
    while True:
        idx = start_idx + 1 + offset
        if idx >= n:
            break
        text = lines[idx].strip()
        if text:
            match = CAPTION_RE.match(text)
            if match:
                return CaptionMatch(
                    raw=text,
                    chapter=int(match["chapter"]),
                    figure=int(match["figure"]),
                    ref=f"{match['chapter']}.{match['figure']}",
                    description=match["desc"],
                    line_index=idx,
                )
            seen_lines += 1
            if seen_lines >= window:
                break
        offset += 1
        if offset > 1000:
            # defensa contra inputs patológicos.
            break
    return None


def italicize_caption(caption: CaptionMatch) -> str:
    """Devuelve la línea italic markdown: ``*<raw>*``."""
    return f"*{caption.raw}*"
