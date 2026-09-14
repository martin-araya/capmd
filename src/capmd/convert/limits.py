"""Límites configurables para una conversión (B5).

``ConversionLimits`` agrupa los cuatro topes que B5 define: tamaño
físico del archivo, cantidad de páginas, tiempo de conversión y umbral
de aviso por páginas. ``parse_size`` es el parser humano (``500M``,
``2G``, ``1024``) que usa la CLI.

Mantener este módulo separado de ``engine.py`` evita que el wrapper de
markitdown se llene de concerns de UX (sufijos humanos, defaults
editables).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["DEFAULT_LIMITS", "ConversionLimits", "parse_size"]


@dataclass(frozen=True)
class ConversionLimits:
    """Topes que aplica el Engine antes y durante una conversión.

    Attributes
    ----------
    max_size_bytes:
        Tamaño máximo del archivo en bytes. Superarlo → ``InputTooLarge``.
    max_pages:
        Cantidad máxima de páginas (solo PDF). Superarlo →
        ``InputTooLarge``.
    timeout_seconds:
        Tiempo máximo de la llamada a markitdown. Superarlo →
        ``ConversionFailed`` (con ``signal.alarm`` en POSIX).
    warn_pages:
        Umbral para imprimir un warning a stderr/log cuando el PDF
        supera esta cantidad de páginas. No bloquea la conversión.
    """

    max_size_bytes: int = 524_288_000  # 500 MB decimal
    max_pages: int = 5_000
    timeout_seconds: int = 600
    warn_pages: int = 500

    def __post_init__(self) -> None:
        if self.max_size_bytes < 1:
            raise ValueError(f"max_size_bytes must be >= 1, got {self.max_size_bytes}")
        if self.max_pages < 1:
            raise ValueError(f"max_pages must be >= 1, got {self.max_pages}")
        if self.timeout_seconds < 1:
            raise ValueError(f"timeout_seconds must be >= 1, got {self.timeout_seconds}")
        if self.warn_pages < 1:
            raise ValueError(f"warn_pages must be >= 1, got {self.warn_pages}")


DEFAULT_LIMITS = ConversionLimits()


_SIZE_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kKmMgG]?)\s*$")
_SIZE_MULTIPLIERS = {
    "": 1,
    "k": 1_000,
    "K": 1_000,
    "m": 1_000_000,
    "M": 1_000_000,
    "g": 1_000_000_000,
    "G": 1_000_000_000,
}


def parse_size(text: str) -> int:
    """Convierte un string humano de tamaño a bytes.

    Acepta sufijo opcional ``K`` / ``M`` / ``G`` (case-insensitive,
    multiplicador decimal). Sin sufijo = bytes. ``"500M"`` → 500_000_000.

    Raises
    ------
    ValueError:
        Si el texto no matchea el patrón, es negativo o el resultado
        excede ``2**63 - 1``.
    """
    if not isinstance(text, str):
        raise ValueError(f"size must be a string, got {type(text).__name__}")
    match = _SIZE_PATTERN.match(text)
    if match is None:
        raise ValueError(f"tamaño inválido: {text!r} (ej: 500M, 2G, 1024)")
    number, suffix = match.groups()
    multiplier = _SIZE_MULTIPLIERS[suffix]
    raw = float(number) * multiplier
    if raw < 0:
        raise ValueError(f"tamaño inválido: {text!r} (negativo)")
    bytes_ = int(raw)
    if bytes_ < 1:
        raise ValueError(f"tamaño inválido: {text!r} (menor a 1 byte)")
    if bytes_ > 2**63 - 1:
        raise ValueError(f"tamaño inválido: {text!r} (overflow)")
    return bytes_
