"""Ligaduras tipográficas latin y sus reemplazos ASCII.

Todas son ligaduras "presentation" del bloque Alphabetic Presentation Forms
(U+FB00–U+FB06) que algunos libros traen porque el kerning tipográfico las
prefiere. ``capmd`` las normaliza a su forma ASCII explícita.
"""

from __future__ import annotations

__all__ = ["LIGATURES_MAP"]

LIGATURES_MAP: dict[str, str] = {
    "ﬁ": "fi",  # U+FB01
    "ﬂ": "fl",  # U+FB02
    "ﬃ": "ffi",  # U+FB03
    "ﬄ": "ffl",  # U+FB04
    "ﬅ": "st",  # U+FB05 (long s + t)
    "ﬆ": "st",  # U+FB06
}
