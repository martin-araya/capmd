"""Wrappers sobre markitdown."""

from capmd.convert.engine import Engine
from capmd.convert.formats import SUPPORTED_FORMATS, FormatInfo, known_extensions
from capmd.convert.limits import DEFAULT_LIMITS, ConversionLimits, parse_size
from capmd.convert.page_markers import (
    PAGE_MARKER_RE,
    PAGE_MARKER_TEMPLATE,
    insert_page_markers,
    join_pages,
    split_by_page_markers,
    strip_page_markers,
)

__all__ = [
    "DEFAULT_LIMITS",
    "PAGE_MARKER_RE",
    "PAGE_MARKER_TEMPLATE",
    "SUPPORTED_FORMATS",
    "ConversionLimits",
    "Engine",
    "FormatInfo",
    "insert_page_markers",
    "join_pages",
    "known_extensions",
    "parse_size",
    "split_by_page_markers",
    "strip_page_markers",
]
