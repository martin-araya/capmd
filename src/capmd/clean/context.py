"""Contexto inmutable que viaja entre cleaners durante un run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from capmd.models import Format, PageRange, SourceDoc

__all__ = ["CleanContext"]


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})  # pragma: no cover
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class CleanContext:
    """Metadatos disponibles para los cleaners.

    ``config`` y ``extra`` se almacenan como ``MappingProxyType`` para
    garantizar inmutabilidad lógica incluso si el caller muta el dict
    original después de construir el contexto.

    ``page_font_sizes`` es una tupla ``(page_1, page_2, ...)`` donde
    cada ``page_N`` es la tupla de font sizes por char de esa página
    (orden de pypdfium2 ``count_chars``). Se popula por el integration
    layer cuando el input es un PDF procesado con pypdfium2; ``None``
    para stdin, EPUB u otros formatos.
    """

    source: SourceDoc
    format: Format
    page_range: PageRange | None = None
    config: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    page_markers: tuple[str, ...] = ()
    page_font_sizes: tuple[tuple[float, ...], ...] | None = None
    page_font_names: tuple[tuple[str, ...], ...] | None = None
    profile: str | None = None
    extra: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.source is None:
            raise ValueError("source is required")
        if self.page_range is not None and not isinstance(self.page_range, PageRange):
            raise TypeError(
                f"page_range must be PageRange or None, got {type(self.page_range).__name__}"
            )
        object.__setattr__(self, "config", _freeze_mapping(self.config))
        object.__setattr__(self, "extra", _freeze_mapping(self.extra))
