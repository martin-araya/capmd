r"""Reconstrucción de headings (D7).

Dos estrategias combinadas:

1. **Font-size aware** (cuando ``page_font_sizes`` está disponible):
   pypdfium2 provee font size por char; el ratio contra la mediana del
   body clasifica la línea en H1-H4.

2. **Regex fallback** (siempre activo):

   - ``Chapter N[:.]? ...`` / ``Capítulo N[:.]? ...`` -> H1
   - ALL CAPS (>=3 chars) -> H1
   - ``X.Y.Z ...`` -> H3 (antes que H2 para no matchear como H2)
   - ``X.Y ...`` -> H2

Líneas que ya empiezan con ``#`` no se tocan. Detección de code
blocks queda para D9.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext
from capmd.convert.page_markers import join_pages, split_by_page_markers

__all__ = [
    "DEFAULT_NAME",
    "DEFAULT_OPTIONS",
    "RE_H1_ALLCAPS",
    "RE_H1_CHAPTER",
    "RE_H2_NUMBERED",
    "RE_H3_NUMBERED",
    "HeadingOptions",
    "HeadingReconstructor",
    "detect_heading_level",
    "reconstruct_headings",
]

DEFAULT_NAME = "headings"

RE_H1_CHAPTER = re.compile(r"^(?:Chapter|Cap[ií]tulo|Cap\.?)\s+\d+", re.IGNORECASE)
RE_H1_ALLCAPS = re.compile(r"^[A-Z][A-Z\s]{2,80}$")
RE_H2_NUMBERED = re.compile(r"^\d+\.\d+\s+\S")
RE_H3_NUMBERED = re.compile(r"^\d+\.\d+\.\d+\s+\S")


@dataclass(frozen=True)
class HeadingOptions:
    """Parámetros del reconstructor de headings."""

    body_median_threshold_h1: float = 1.6
    body_median_threshold_h2: float = 1.3
    body_median_threshold_h3: float = 1.15
    body_median_threshold_h4: float = 1.05
    min_length: int = 1
    max_length: int = 200
    blank_line_before: bool = True


DEFAULT_OPTIONS = HeadingOptions()


def _classify_by_font(font_size: float, body_median: float, options: HeadingOptions) -> int:
    if body_median <= 0:
        return 0
    ratio = font_size / body_median
    if ratio >= options.body_median_threshold_h1:
        return 1
    if ratio >= options.body_median_threshold_h2:
        return 2
    if ratio >= options.body_median_threshold_h3:
        return 3
    if ratio >= options.body_median_threshold_h4:
        return 4
    return 0


def _classify_by_regex(line: str) -> int:
    if RE_H1_CHAPTER.match(line):
        return 1
    if RE_H3_NUMBERED.match(line):
        return 3
    if RE_H2_NUMBERED.match(line):
        return 2
    if RE_H1_ALLCAPS.match(line):
        return 1
    return 0


def detect_heading_level(
    line: str,
    *,
    font_size: float | None = None,
    body_median: float | None = None,
    options: HeadingOptions = DEFAULT_OPTIONS,
) -> int:
    """Devuelve 1-4 si ``line`` es heading, ``0`` si no.

    Font-size tiene prioridad cuando ambos datos están disponibles y
    produce un nivel (>0). Si produce 0, cae al regex.
    """
    if not line or not line.strip():
        return 0
    if line.lstrip().startswith("#"):
        return 0
    if len(line) < options.min_length or len(line) > options.max_length:
        return 0

    font_level = 0
    if font_size is not None and body_median is not None and body_median > 0:
        font_level = _classify_by_font(font_size, body_median, options)

    if font_level > 0:
        return font_level
    return _classify_by_regex(line)


def _find_line_char_index(line: str, page_text: str, search_from: int) -> int | None:
    """Busca la siguiente aparición de ``line`` en ``page_text`` desde ``search_from``.

    Si la línea tiene contenido vacío o solo whitespace, devuelve ``None``.
    """
    stripped = line.strip()
    if not stripped:
        return None
    pos = page_text.find(stripped, search_from)
    if pos < 0:
        return None
    return pos


def _line_font_size(
    line: str,
    page_text: str,
    page_font_sizes: tuple[float, ...] | None,
    search_from: int,
) -> float | None:
    if page_font_sizes is None or not page_font_sizes:
        return None
    char_idx = _find_line_char_index(line, page_text, search_from)
    if char_idx is None or char_idx >= len(page_font_sizes):
        return None
    return page_font_sizes[char_idx]


def _process_page(
    page: str,
    page_font_sizes: tuple[float, ...] | None,
    body_median: float | None,
    options: HeadingOptions,
) -> tuple[str, int]:
    lines = page.splitlines()
    out_lines: list[str] = []
    n_headings = 0
    search_from = 0

    for line in lines:
        font = _line_font_size(line, page, page_font_sizes, search_from)
        if font is not None:
            stripped = line.strip()
            if stripped:
                search_from = page.find(stripped, search_from) + len(stripped)

        level = detect_heading_level(line, font_size=font, body_median=body_median, options=options)
        if level > 0:
            prefix = "#" * level + " "
            out_lines.append(prefix + line)
            n_headings += 1
        else:
            out_lines.append(line)

    return "\n".join(out_lines), n_headings


def _ensure_blank_before_headings(text: str) -> str:
    """Inserta ``\\n`` antes de cualquier línea que empiece con ``#``.

    Solo si la línea anterior no está ya en blanco. No modifica
    líneas vacías ni el contenido de cada heading.
    """
    if not text:
        return text
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if line.startswith("#") and out and out[-1] != "" and not out[-1].startswith("#"):
            out.append("")
        out.append(line)
    return "\n".join(out)


def reconstruct_headings(
    text: str,
    *,
    page_font_sizes: tuple[tuple[float, ...], ...] | None = None,
    options: HeadingOptions = DEFAULT_OPTIONS,
) -> str:
    """Aplica ``#`` a las líneas detectadas como headings."""
    if not text:
        return text

    if page_font_sizes is not None:
        all_sizes: list[float] = []
        for sizes in page_font_sizes:
            all_sizes.extend(s for s in sizes if s and s > 0)
        body_median = statistics.median(all_sizes) if all_sizes else None

        pages = split_by_page_markers(text)
        out_pages: list[str] = []
        total_headings = 0
        for page_idx, page in enumerate(pages):
            pf = page_font_sizes[page_idx] if page_idx < len(page_font_sizes) else None
            processed, n = _process_page(page, pf, body_median, options)
            out_pages.append(processed)
            total_headings += n
        joined = join_pages(out_pages)
    else:
        processed, total_headings = _process_page(text, None, None, options)
        joined = processed

    if options.blank_line_before:
        joined = _ensure_blank_before_headings(joined)
    return joined


class HeadingReconstructor(Cleaner):
    """Reconstructor de headings (D7)."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        options: HeadingOptions | None = None,
    ) -> None:
        self._options = options or DEFAULT_OPTIONS
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    @property
    def options(self) -> HeadingOptions:
        return self._options

    def _apply(self, md: str, ctx: CleanContext) -> CleanResult:
        out = reconstruct_headings(md, page_font_sizes=ctx.page_font_sizes, options=self._options)
        if out == md:
            return CleanResult(text=md, changes=0)
        n_headings = sum(1 for line in out.splitlines() if line.startswith("#")) - sum(
            1 for line in md.splitlines() if line.startswith("#")
        )
        return CleanResult(text=out, changes=max(n_headings, 0))
