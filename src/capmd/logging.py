"""Configuración del logging de capmd.

Reglas (agent.md):
- Salida a stderr (stdout es solo para el resultado).
- Nivel por defecto WARNING; -v = INFO; -vv = DEBUG.
- ``--quiet`` (H1) sube el nivel a CRITICAL para silenciar TODO lo que
  vaya por el logger de capmd.
- ``configure_logging()`` y ``configure_quiet()`` son idempotentes:
  usarlas en cada arranque del CLI.

Para mensajes desde otros módulos::

    from capmd.logging import get_logger
    logger = get_logger(__name__)
    logger.debug("...")
"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "capmd"
_LEVEL_BY_VERBOSE: tuple[int, ...] = (logging.WARNING, logging.INFO, logging.DEBUG)
_FORMAT = "%(levelname)s: %(name)s: %(message)s"


def configure_logging(verbose: int) -> None:
    """Configura el logger ``capmd`` según el conteo de ``--verbose``.

    Idempotente: limpia handlers previos antes de instalar el nuevo.
    """
    level = _LEVEL_BY_VERBOSE[min(verbose, len(_LEVEL_BY_VERBOSE) - 1)]

    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def configure_quiet() -> None:
    """Sube el logger ``capmd`` a CRITICAL para ``--quiet`` (H1).

    Idempotente: conserva el handler existente (sigue yendo a stderr)
    pero ningún nivel por debajo de CRITICAL se renderiza. Llamarla
    DESPUÉS de ``configure_logging`` para que pise el nivel resultante
    de ``-v``.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(logging.CRITICAL)


def get_logger(name: str | None = None) -> logging.Logger:
    """Devuelve un sub-logger de ``capmd`` (o el raíz si ``name`` es None).

    Acepta tanto ``get_logger("cli")`` como ``get_logger("capmd.cli")`` —
    el prefijo ``capmd.`` se aplica una sola vez.
    """
    if name is None:
        return logging.getLogger(_LOGGER_NAME)
    if name.startswith(f"{_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
