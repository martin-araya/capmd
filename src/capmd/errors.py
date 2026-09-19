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


class PermissionDenied(CapmdError):
    """El usuario no tiene permisos de escritura sobre el destino.

    FIX-6: cuando ``capmd convert`` intenta escribir a un directorio
    sin permisos de escritura para el usuario actual, lanza esta
    subclase en lugar del genérico :class:`IOError`. El ``hint``
    apunta al path real que falló (no a un ``images/`` simbólico).
    """

    exit_code = 5


class ChapterDetectionFailed(CapmdError):
    """La heurística de outline no encontró capítulos en un PDF sin outline."""

    exit_code = 4


class AzureBackendMissing(CapmdError):
    """El binario ``markitdown`` no está en PATH (K4).

    capmd usa ``markitdown`` como subprocess para enrutar a Azure
    Doc Intelligence / Content Understanding. Si no se encuentra en
    PATH, este error se levanta antes de intentar nada.
    """

    exit_code = 3


class AzureConversionFailed(CapmdError):
    """El subprocess de ``markitdown`` con backend Azure falló (K4).

    Captura el stderr del subprocess para dar contexto actionable
    (e.g., falta el extra de Azure, timeout, endpoint inválido).
    """

    exit_code = 5
