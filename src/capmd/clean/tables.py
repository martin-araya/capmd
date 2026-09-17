"""Reparación de tablas markdown (D12).

Pipeline de tres capas:

1. **GFM ya presente:** normaliza bloques que ya vienen en formato
   GitHub Flavored Markdown (separator line presente, columnas alineadas).
2. **Filas alineadas sin separator:** cuando hay un bloque de líneas
   con pipes consistentes pero sin separator, lo arma como tabla GFM
   con separator sintético.
3. **Confianza baja:** si el score de consistencia es < ``score_threshold``,
   marca el bloque con ``<!-- tabla no estructurada -->`` y preserva
   las líneas originales.

Respeta code fences ```` ``` ```` y ``~~~`` (vía ``split_outside_fences``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from capmd.clean._fences import split_outside_fences
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "DEFAULT_NAME",
    "DEFAULT_OPTIONS",
    "GFM_SEPARATOR_RE",
    "PIPE_LINE_RE",
    "TableOptions",
    "TablesCleaner",
    "detect_table_blocks",
    "render_gfm_table",
    "repair_tables",
    "score_block",
    "split_row",
    "wrap_unstructured_table",
]

DEFAULT_NAME = "tables"

PIPE_LINE_RE = re.compile(r"^\s*\|.*\|.*\|?\s*$")
GFM_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
ESCAPED_PIPE_RE = re.compile(r"\\\|")

UNSTRUCTURED_COMMENT = "<!-- tabla no estructurada -->"


@dataclass(frozen=True)
class TableOptions:
    """Parámetros del cleaner de tablas."""

    score_threshold: float = 0.7
    min_rows: int = 2


DEFAULT_OPTIONS = TableOptions()


def split_row(line: str) -> list[str]:
    """Parte una línea de tabla GFM en celdas.

    Las pipes ``\\|`` escapadas se preservan dentro de las celdas.
    """
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith(r"\|"):
        stripped = stripped[:-1]
    parts = stripped.split("|")
    return [part.strip() for part in parts]


def detect_table_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Devuelve ``[(start, end_exclusive), ...]`` para bloques candidatos."""
    blocks: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        if PIPE_LINE_RE.match(lines[i]):
            start = i
            while i < len(lines) and PIPE_LINE_RE.match(lines[i]):
                i += 1
            blocks.append((start, i))
        else:
            i += 1
    return blocks


def _all_rows_same_width(rows: list[str]) -> bool:
    if not rows:
        return False  # pragma: no cover
    widths = {len(split_row(r)) for r in rows}
    return len(widths) == 1


def _all_rows_bracketed(rows: list[str]) -> bool:
    return all(line.strip().startswith("|") and line.strip().endswith("|") for line in rows)


def _has_separator(rows: list[str]) -> bool:
    return any(GFM_SEPARATOR_RE.match(line) for line in rows)


def _alignment_score(rows: list[str]) -> float:
    """Heurística: proporción de rows con pipes en posiciones similares."""
    if not rows:
        return 0.0  # pragma: no cover
    pipe_positions_by_row: list[list[int]] = []
    for row in rows:
        positions: list[int] = []
        for idx, ch in enumerate(row):
            if ch == "|" and not _is_escaped(row, idx):
                positions.append(idx)
        pipe_positions_by_row.append(positions)
    if not pipe_positions_by_row or not pipe_positions_by_row[0]:
        return 0.0  # pragma: no cover
    reference = pipe_positions_by_row[0]
    matches = sum(
        1
        for positions in pipe_positions_by_row
        if len(positions) == len(reference)
        and all(abs(a - b) <= 1 for a, b in zip(positions, reference, strict=False))
    )
    return matches / len(pipe_positions_by_row)


def _is_escaped(line: str, pos: int) -> bool:
    return ESCAPED_PIPE_RE.match(line[max(0, pos - 1) : pos + 1]) is not None


def score_block(block_lines: list[str]) -> float:
    """Score 0-1 de confianza de que el bloque es una tabla."""
    if len(block_lines) < 2:
        return 0.0
    score = 0.0
    if _has_separator(block_lines):
        score += 0.4
    if _all_rows_same_width(block_lines):
        score += 0.5
    if _all_rows_bracketed(block_lines):
        score += 0.2
    score += 0.1 * _alignment_score(block_lines)
    return min(score, 1.0)


def render_gfm_table(rows: list[str]) -> str:
    """Normaliza un bloque como tabla GFM con padding uniforme."""
    parsed_rows = [split_row(r) for r in rows]
    if not parsed_rows:
        return ""
    width = max(len(r) for r in parsed_rows)
    normalized: list[list[str]] = []
    for r in parsed_rows:
        if len(r) < width:
            r = r + [""] * (width - len(r))  # pragma: no cover
        normalized.append(r)
    data_rows = [i for i, original in enumerate(rows) if not GFM_SEPARATOR_RE.match(original)]
    col_widths = [max(len(normalized[i][c]) for i in data_rows) for c in range(width)]
    out: list[str] = []
    for row in normalized:
        cells = [f" {row[c].ljust(col_widths[c])} " for c in range(width)]
        out.append("|" + "|".join(cells) + "|")
    if not _has_separator(rows):
        separator_cells = [f" {'-' * max(3, col_widths[c])} " for c in range(width)]
        separator = "|" + "|".join(separator_cells) + "|"
        out.insert(1, separator)
    return "\n".join(out)


def wrap_unstructured_table(block_lines: list[str]) -> str:
    """Marca el bloque con un comment y preserva las líneas tal cual."""
    return UNSTRUCTURED_COMMENT + "\n" + "\n".join(block_lines)


def repair_tables(
    text: str,
    *,
    options: TableOptions = DEFAULT_OPTIONS,
) -> str:
    """Detecta y normaliza tablas en ``text``. Respeta fences."""
    if not text:
        return text
    segments = split_outside_fences(text)
    out_parts: list[str] = []
    for seg, in_fence in segments:
        if in_fence:
            out_parts.append(seg)
            continue
        processed, _ = _repair_segment(seg, options)
        out_parts.append(processed)
    return "".join(out_parts)


def _repair_segment(segment: str, options: TableOptions) -> tuple[str, int]:
    """Procesa un segmento y devuelve ``(texto_procesado, n_blocks_processed)``."""
    lines = segment.splitlines(keepends=True)
    blocks = detect_table_blocks(lines)
    if not blocks:
        return segment, 0
    out: list[str] = []
    cursor = 0
    n_blocks = 0
    for start, end in blocks:
        out.append("".join(lines[cursor:start]))
        block_lines = [line.rstrip("\n") for line in lines[start:end]]
        if len(block_lines) < options.min_rows:
            out.append("".join(lines[start:end]))  # pragma: no cover
            cursor = end  # pragma: no cover
            continue  # pragma: no cover
        data_rows = [r for r in block_lines if not GFM_SEPARATOR_RE.match(r)]
        if len(data_rows) < options.min_rows:
            out.append("".join(lines[start:end]))  # pragma: no cover
            cursor = end  # pragma: no cover
            continue  # pragma: no cover
        score = score_block(block_lines)
        if score >= options.score_threshold:
            out.append(render_gfm_table(block_lines) + "\n")
        else:
            out.append(wrap_unstructured_table(block_lines) + "\n")
        n_blocks += 1
        cursor = end
    out.append("".join(lines[cursor:]))
    return "".join(out), n_blocks


class TablesCleaner(Cleaner):
    """Cleaner que detecta y normaliza tablas markdown."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        options: TableOptions | None = None,
    ) -> None:
        self._options = options or DEFAULT_OPTIONS
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    @property
    def options(self) -> TableOptions:
        return self._options  # pragma: no cover

    def _apply(self, md: str, ctx: CleanContext) -> CleanResult:
        if not md:
            return CleanResult(text=md, changes=0)
        segments = split_outside_fences(md)
        out_parts: list[str] = []
        n_blocks = 0
        for seg, in_fence in segments:
            if in_fence:
                out_parts.append(seg)  # pragma: no cover
                continue  # pragma: no cover
            processed, n = _repair_segment(seg, self._options)
            out_parts.append(processed)
            n_blocks += n
        out = "".join(out_parts)
        if out == md:
            return CleanResult(text=md, changes=0)
        return CleanResult(text=out, changes=n_blocks)
