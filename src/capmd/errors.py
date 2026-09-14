"""Excepciones propias de capmd y sus exit codes.

Cada subclase tiene un `exit_code` estable (1-5). El handler global en
`cli.py` los mapea a `sys.exit(code)` tras imprimir el mensaje con rich.

Regla de agent.md: cada CapmdError dice qué pasó y qué hacer (vía `hint`).
"""

from __future__ import annotations

from typing import ClassVar


class CapmdError(Exception):
    """Base de todos los errores de capmd."""

    exit_code: ClassVar[int] = 1
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class SourceNotFound(CapmdError):
    """El archivo de entrada no existe, no es legible, o no es un archivo regular."""

    exit_code = 2


class UnsupportedFormat(CapmdError):
    """Extensión de archivo no soportada por capmd (o falta el extra de markitdown)."""

    exit_code = 3


class RangeOutOfBounds(CapmdError):
    """Rango de páginas solicitado fuera de los límites del PDF."""

    exit_code = 4


class ConversionFailed(CapmdError):
    """markitdown (o un motor alternativo) falló al convertir el archivo."""

    exit_code = 5


class InputTooLarge(CapmdError):
    """El archivo excede --max-size o --max-pages antes de convertir."""

    exit_code = 6


class IOError(CapmdError):
    """Error de filesystem al escribir o leer artefactos de capmd."""

    exit_code = 7


class ChapterDetectionFailed(CapmdError):
    """La heurística de outline no encontró capítulos en un PDF sin outline."""

    exit_code = 4
