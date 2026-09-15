"""Extracción, filtrado y anclaje de imágenes embebidas en PDFs (E1-E5).

API pública:

- :class:`ExtractOptions`: opciones inmutables (formato, max_width).
- :class:`ImageCandidate`: imagen decodificada en memoria con metadata.
- :class:`ExtractResult`: ``(figures, report)`` retornado por
  :func:`extract_figures`.
- :func:`extract_figures`: atajo con pipeline completo (E1+E2).
- :func:`extract_candidates`: solo extrae sin filtrar.
- :func:`write_figures`: persiste una lista ya filtrada.
- :class:`FilterDecision`, :class:`FilterRules`, :class:`FilterReport`:
  superficies del filtro (E2).
- :func:`filter_candidates`: aplica filtros sobre una lista in-memory.
- :func:`anchor_figures`: inserta ``![]()`` en el markdown con anclaje posicional (E4)
  y, cuando detecta un caption cercano (E5), lo usa como alt y emite una línea italic.
- :func:`default_alt_text`: lee :attr:`Figure.caption` (E5) o devuelve "".
- :class:`CaptionMatch`, :func:`find_caption_in_window`, :func:`italicize_caption`,
  :data:`CAPTION_RE`: superficies de la detección de captions (E5).
"""

from capmd.images.anchor import (
    FigurePlaceholder,
    anchor_figures,
    default_alt_text,
    extract_figure_placeholders,
    format_placeholder,
    insert_image_placeholders,
)
from capmd.images.captions import (
    CAPTION_RE,
    CaptionMatch,
    find_caption_in_window,
    italicize_caption,
)
from capmd.images.extract import (
    SUPPORTED_IMAGE_FORMATS,
    ExtractOptions,
    ExtractResult,
    ImageCandidate,
    extract_candidates,
    extract_figures,
    make_figure_name,
    write_figures,
)
from capmd.images.filter import FilterDecision, FilterReport, FilterRules, filter_candidates

__all__ = [
    "CAPTION_RE",
    "SUPPORTED_IMAGE_FORMATS",
    "CaptionMatch",
    "ExtractOptions",
    "ExtractResult",
    "FigurePlaceholder",
    "FilterDecision",
    "FilterReport",
    "FilterRules",
    "ImageCandidate",
    "anchor_figures",
    "default_alt_text",
    "extract_candidates",
    "extract_figure_placeholders",
    "extract_figures",
    "filter_candidates",
    "find_caption_in_window",
    "format_placeholder",
    "insert_image_placeholders",
    "italicize_caption",
    "make_figure_name",
    "write_figures",
]
