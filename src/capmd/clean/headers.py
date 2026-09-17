"""Header/footer repetidos (D4).

Consume markdown con centinelas ``<!-- page N -->`` (insertados por
D5 / ``Engine.convert_pages``) y elimina líneas que aparecen en
``>= threshold`` de las páginas en posición inicial/final.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext
from capmd.convert.page_markers import (
    insert_page_markers,
    join_pages,
    split_by_page_markers,
    strip_page_markers,
)

__all__ = [
    "DEFAULT_NAME",
    "DEFAULT_OPTIONS",
    "HeaderFooterCleaner",
    "HeaderFooterOptions",
    "detect_headers_footers",
    "normalize_line",
    "remove_headers_footers",
]

DEFAULT_NAME = "headers"

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class HeaderFooterOptions:
    """Parámetros del detector de headers/footers."""

    header_lines: int = 3
    footer_lines: int = 3
    threshold: float = 0.6
    min_pages: int = 2
    keep_markers: bool = False


DEFAULT_OPTIONS = HeaderFooterOptions()


def normalize_line(line: str) -> str:
    """Colapsa whitespace interno y strip extremos."""
    return _WHITESPACE_RE.sub(" ", line.strip())


def _candidate_lines(page: str, count: int, *, from_top: bool) -> list[str]:
    """Devuelve las primeras/últimas ``count`` líneas no vacías de ``page``."""
    lines = [line for line in page.splitlines() if line.strip()]  # pragma: no cover
    if from_top:  # pragma: no cover
        return lines[:count]  # pragma: no cover
    return lines[-count:] if count > 0 else []  # pragma: no cover


def detect_headers_footers(
    pages: list[str],
    *,
    options: HeaderFooterOptions = DEFAULT_OPTIONS,
) -> tuple[frozenset[str], frozenset[str]]:
    """Detecta headers y footers que aparecen en ``>= threshold`` páginas.

    Devuelve ``(headers, footers)``. En páginas cortas donde ``top N`` y
    ``bottom N`` se solapan, las líneas en la intersección se cuentan
    solo como header (no se duplican como footer).
    """
    n = len(pages)
    if n < options.min_pages:
        return frozenset(), frozenset()
    threshold_count = math.ceil(options.threshold * n)

    header_counter: Counter[str] = Counter()
    footer_counter: Counter[str] = Counter()

    for page in pages:
        lines = [line for line in page.splitlines() if line.strip()]
        if not lines:  # pragma: no cover - defensivo
            continue

        top_keys: set[str] = set()
        for line in lines[: options.header_lines]:
            key = normalize_line(line)
            if key:
                top_keys.add(key)

        bottom_keys: set[str] = set()
        for line in lines[-options.footer_lines :]:
            key = normalize_line(line)
            if key and key not in top_keys:
                bottom_keys.add(key)

        for key in top_keys:
            header_counter[key] += 1
        for key in bottom_keys:
            footer_counter[key] += 1

    headers = frozenset(k for k, c in header_counter.items() if c >= threshold_count)
    footers = frozenset(k for k, c in footer_counter.items() if c >= threshold_count)
    return headers, footers


def _strip_matching(page: str, banned: Iterable[str]) -> str:
    banned_set = frozenset(banned)
    out_lines: list[str] = []
    for line in page.splitlines():
        if normalize_line(line) in banned_set:
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def remove_headers_footers(
    text: str,
    *,
    options: HeaderFooterOptions = DEFAULT_OPTIONS,
) -> str:
    """Detecta y elimina headers/footers en ``text``.

    Asume que ``text`` contiene centinelas ``<!-- page N -->``. Si no
    los contiene, devuelve el texto sin modificar.
    """
    if "<!-- page" not in text:
        return text
    pages = split_by_page_markers(text)
    if not pages:
        return text  # pragma: no cover
    headers, footers = detect_headers_footers(pages, options=options)
    banned = headers | footers
    cleaned_pages = [_strip_matching(p, banned) for p in pages]
    if options.keep_markers:
        return insert_page_markers(cleaned_pages)
    return join_pages(cleaned_pages)


class HeaderFooterCleaner(Cleaner):
    """Cleaner de headers/footers repetidos."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        options: HeaderFooterOptions | None = None,
    ) -> None:
        self._options = options or DEFAULT_OPTIONS
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    @property
    def options(self) -> HeaderFooterOptions:
        return self._options  # pragma: no cover

    def _apply(self, md: str, ctx: CleanContext) -> CleanResult:
        if "<!-- page" not in md:
            return CleanResult(text=md, changes=0)
        pages = split_by_page_markers(md)
        if len(pages) < self._options.min_pages:
            if self._options.keep_markers:
                return CleanResult(text=md, changes=0)  # pragma: no cover
            return CleanResult(text=strip_page_markers(md), changes=0)
        headers, footers = detect_headers_footers(pages, options=self._options)
        n_changes = len(headers) + len(footers)
        cleaned = remove_headers_footers(md, options=self._options)
        return CleanResult(text=cleaned, changes=n_changes)
