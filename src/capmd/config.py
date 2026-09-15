"""Loader minimalista de configuración TOML y entry points de integración.

Alcance:
  - TOML overrides para filtros de imágenes (E2).
  - Re-export de :func:`capmd.llm.build_llm_client` para que los tests
    puedan monkeypatchearla desde un lugar estable (``capmd.config``).

G1/G3 ampliarán este módulo con la jerarquía completa de configuración
(precedencia CLI > env > project > global > defaults) y perfiles por
libro basados en hash del PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from capmd.llm import DEFAULT_MODELS as LLM_DEFAULT_MODELS  # noqa: F401  -- re-export
from capmd.llm import build_llm_client
from capmd.logging import get_logger

logger = get_logger(__name__)

__all__ = ["build_llm_client", "load_image_filter_overrides"]

_GLOBAL_TOML = Path.home() / ".config" / "capmd" / "config.toml"
_PROJECT_TOML = Path("capmd.toml")

_IMAGE_KEYS: frozenset[str] = frozenset({"min_size", "repeat_threshold", "background_coverage"})


def _read_toml(path: Path) -> dict[str, Any]:
    """Lee ``[images]`` de un TOML si existe.

    Devuelve ``{}`` si el archivo no existe, si ``tomllib`` no está
    disponible (Python < 3.11), o si el archivo está malformado (se
    loggea un warning en este último caso).
    """
    if not path.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        logger.debug("tomllib no disponible; saltando %s", path)
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as exc:  # toleramos cualquier error de parseo
        logger.warning("no se pudo leer %s: %s; usando defaults", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    section = data.get("images", {})
    return section if isinstance(section, dict) else {}


def load_image_filter_overrides() -> dict[str, Any]:
    """Devuelve overrides para filtros de imágenes con precedencia project > global.

    Solo se devuelven claves dentro de :data:`_IMAGE_KEYS`; claves
    desconocidas se ignoran silenciosamente.

    La capa de precedencia completa (CLI > env > project > global >
    defaults) la arma el caller (CLI de ``capmd convert``).
    """
    merged: dict[str, Any] = {}
    for source in (_GLOBAL_TOML, _PROJECT_TOML):
        section = _read_toml(source)
        for key in _IMAGE_KEYS:
            if key in section:
                merged[key] = section[key]
    return merged
