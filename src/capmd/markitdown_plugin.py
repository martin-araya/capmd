"""Plugin de ``markitdown`` que aplica el pipeline de cleaners de ``capmd``.

``capmd`` se declara a sí mismo como entry-point en el grupo
``markitdown.plugin``, de modo que al ejecutar ``markitdown --use-plugins``
queda registrado un :class:`DocumentConverter` que limpia streams de
markdown usando el pipeline por defecto de capmd.

El plugin corre fuera del CLI de ``capmd``, así que no consulta la
configuración TOML ni variables de entorno del usuario: aplica
:func:`capmd.clean.default_pipeline` con todos sus cleaners, en orden.

Workflow típico::

    # Limpieza directa de un .md
    markitdown archivo.md --use-plugins -o limpio.md

    # Limpieza en dos pasadas para un PDF
    markitdown libro.pdf -o tmp.md
    markitdown tmp.md --use-plugins -o limpio.md
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from markitdown import DocumentConverter, DocumentConverterResult, StreamInfo

import capmd
from capmd.clean.context import CleanContext
from capmd.clean.pipeline import Pipeline, default_pipeline
from capmd.models import SourceDoc

__all__ = [
    "PLUGIN_NAME",
    "CleanersMarkItDownPlugin",
    "MarkdownCleanerConverter",
]

PLUGIN_NAME = "capmd-cleaners"

_MARKDOWN_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".mkd", ".mkdn"})
_MARKDOWN_MIMETYPES: frozenset[str] = frozenset({"text/markdown", "text/x-markdown"})

_SYNTHETIC_SHA256 = "0" * 64

# Misma prioridad que los converters genéricos built-in de markitdown
# (PRIORITY_GENERIC_FILE_FORMAT). Nos insertamos en el pool genérico: los
# específicos (PDF, DOCX, etc.) con priority 0 se prueban primero.
_PLUGIN_PRIORITY: float = 10.0


class MarkdownCleanerConverter(DocumentConverter):
    """``DocumentConverter`` que corre el pipeline de cleaners sobre un markdown.

    Acepta streams con extensión ``.md``/``.markdown``/``.mkd``/``.mkdn``
    o ``mimetype`` ``text/markdown``/``text/x-markdown``. Cualquier otro
    input se ignora para no competir con los converters built-in.
    """

    def accepts(
        self,
        file_stream: Any,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> bool:
        extension = (stream_info.extension or "").lower()
        if extension in _MARKDOWN_EXTENSIONS:
            return True
        mimetype = (stream_info.mimetype or "").lower()
        return mimetype in _MARKDOWN_MIMETYPES

    def convert(
        self,
        file_stream: Any,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        raw = file_stream.read()
        text = (
            raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        )

        pipeline = _get_pipeline()
        ctx = _build_context(stream_info)
        cleaned, _stats = pipeline.run(text, ctx)
        return DocumentConverterResult(markdown=cleaned)


class CleanersMarkItDownPlugin:
    """Plugin de ``markitdown`` declarado como entry-point.

    markitdown descubre este objeto vía ``entry_points(group="markitdown.plugin")``
    y luego invoca :meth:`register_converters` pasándole la instancia de
    :class:`markitdown.MarkItDown` y los kwargs adicionales que el usuario
    pasó al constructor de ``MarkItDown``.
    """

    name: str = PLUGIN_NAME
    version: str = capmd.__version__
    description: str = (
        "Runs capmd's default cleaner pipeline (whitespace, hyphens, "
        "headers/footers, headings, code blocks, etc.) on markdown streams."
    )
    enabled: bool = True

    @classmethod
    def register_converters(cls, markitdown: Any, **kwargs: Any) -> None:
        """Registra :class:`MarkdownCleanerConverter` en la instancia."""
        markitdown.register_converter(
            MarkdownCleanerConverter(),
            priority=_PLUGIN_PRIORITY,
        )


@lru_cache(maxsize=1)
def _get_pipeline() -> Pipeline:
    """Pipeline del plugin (cached a nivel de módulo)."""
    return default_pipeline()


def _build_context(stream_info: StreamInfo) -> CleanContext:
    """Construye un :class:`CleanContext` mínimo para el plugin.

    Sin ``page_font_sizes`` ni ``page_range``: los cleaners que dependen
    de esos datos (heading reconstructor por tamaño de fuente) degradan
    limpio cuando son ``None``.
    """
    source = SourceDoc(
        path=_synthetic_path(stream_info),
        format="other",
        sha256=_SYNTHETIC_SHA256,
        size_bytes=0,
    )
    return CleanContext(source=source, format=source.format)


def _synthetic_path(stream_info: StreamInfo) -> Path:
    """Devuelve un ``Path`` sintético representativo para el plugin."""
    if stream_info.local_path:
        return Path(stream_info.local_path)
    if stream_info.filename:
        return Path(stream_info.filename)
    return Path("plugin-input.md")
