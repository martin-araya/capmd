"""Integración con LLM para descripción de imágenes (fase E6, opcional).

Si el usuario pasa ``--describe-images``, capmd instancia un cliente
LLM (OpenAI / Anthropic / Google) según las variables de entorno
disponibles y lo pasa a :class:`markitdown.MarkItDown` para que el
plugin ``markitdown-ocr`` describa cada imagen embebida. Si no hay
API key, capmd emite UN warning y continúa sin descripción (E5
captions siguen funcionando si están presentes).

La función pública :func:`build_llm_client` es inyectable en tests vía
``monkeypatch.setattr``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DEFAULT_MODELS",
    "ENV_KEYS",
    "LLMConfig",
    "build_llm_client",
    "detect_provider_from_env",
]


# Orden de detección: primero OpenAI, luego Anthropic, luego Google.
ENV_KEYS: tuple[str, ...] = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")

# Modelos default por proveedor (alineados con markitdown-ocr).
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "google": "gemini-1.5-flash",
}


@dataclass(frozen=True)
class LLMConfig:
    """Configuración LLM congelada."""

    provider: str  # "openai" | "anthropic" | "google" | "mock"
    model: str
    api_key: str | None = None
    client: Any = None  # instancia lazy del cliente; puede ser un Mock


def detect_provider_from_env() -> str | None:
    """Detecta el primer proveedor con API key en ``os.environ``.

    Retorna el nombre del proveedor (``"openai"``, ``"anthropic"``,
    ``"google"``) o ``None`` si ninguna variable está seteada.
    """
    mapping = {
        "OPENAI_API_KEY": "openai",
        "ANTHROPIC_API_KEY": "anthropic",
        "GOOGLE_API_KEY": "google",
    }
    for env_var, provider in mapping.items():
        if os.environ.get(env_var):
            return provider
    return None


def build_llm_client(provider: str, model: str | None = None) -> Any:
    """Construye un cliente LLM para ``provider``.

    Parameters
    ----------
    provider:
        ``"openai"``, ``"anthropic"``, ``"google"`` o ``"mock"``
        (solo para tests).
    model:
        Nombre del modelo. Si ``None``, usa el default de
        :data:`DEFAULT_MODELS` para el proveedor.

    Returns
    -------
    Any
        Una instancia de cliente compatible con el protocolo que
        espera :class:`markitdown.MarkItDown`. Para los proveedores
        reales, retorna el objeto cliente del SDK correspondiente.
        Para ``"mock"``, retorna ``None``.

    Raises
    ------
    ImportError
        Si el SDK del proveedor no está instalado.
    ValueError
        Si el proveedor es desconocido.
    """
    if model is None:
        model = DEFAULT_MODELS.get(provider, "")

    if provider == "openai":
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "openai SDK requerido para --describe-images con OpenAI: "
                "pip install 'capmd[llm-openai]'"
            ) from exc
        return openai.OpenAI()

    if provider == "anthropic":
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic SDK requerido para --describe-images con Anthropic: "
                "pip install 'capmd[llm-anthropic]'"
            ) from exc
        return anthropic.Anthropic()

    if provider == "google":
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "google-genai SDK requerido para --describe-images con Google: "
                "pip install 'capmd[llm-google]'"
            ) from exc
        return genai.Client()

    if provider == "mock":
        return None

    raise ValueError(f"proveedor LLM desconocido: {provider!r}")
