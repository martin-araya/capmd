"""Reporte de calidad al final de cada corrida (F6).

Imprime a stderr (separado del markdown a stdout) un ``ReportOutput``
con:

  - ``stats``: páginas procesadas, palabras, headings por nivel,
    figuras, líneas eliminadas por cada cleaner, ratio de borrado
    crudo→limpio, elapsed_seconds, formato del input.
  - ``warnings``: heuristicas automáticas (``no_headings``,
    ``empty_output``, ``no_figures``, ``scanned_pdf``,
    ``over_cleanup``, ``uniform_headings``).
  - ``format``: ``"json"`` (default, parseable) o ``"text"``
    (human-readable, rich).

Single source of truth: los warnings que aparecen en stderr son los
mismos que se persisten en ``capmd.json.warnings`` (F3 schema v2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "CleanerCounts",
    "HeadingCounts",
    "ReportOutput",
    "ReportStats",
    "collect_stats",
    "collect_warnings",
    "render_json",
    "render_text",
]


REPORT_SCHEMA_VERSION = 1

# Heuristicas:
PAGE_COUNT_SCANNED_RATIO_THRESHOLD = 10      # words/page
SCANNED_MIN_PAGES = 2                        # >= 2 páginas para considerarlo escaneado
NO_FIGURES_MIN_PAGES = 5                     # >= 5 páginas para chequear ausencia
NO_HEADINGS_MIN_PAGES = 2                    # >= 2 páginas (≠ 1 sola página sin TOC)
OVER_CLEANUP_RATIO = 0.5                     # 50% del contenido borrado
WORDS_RE = re.compile(r"\b\w+\b", re.UNICODE)
HEADING_RE = re.compile(r"(?m)^(#{1,6}) ")
MULTI_H2_AND_H3 = {"##", "###"}


@dataclass(frozen=True)
class HeadingCounts:
    """Cantidad de headings por nivel."""

    h1: int = 0
    h2: int = 0
    h3: int = 0
    h4: int = 0
    h5: int = 0
    h6: int = 0

    @classmethod
    def from_markdown(cls, markdown: str) -> HeadingCounts:
        c = {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0}
        for m in HEADING_RE.finditer(markdown or ""):
            c[f"h{len(m.group(1))}"] += 1
        return cls(**c)

    @property
    def total(self) -> int:
        return self.h1 + self.h2 + self.h3 + self.h4 + self.h5 + self.h6

    @property
    def non_h1(self) -> int:
        return self.h2 + self.h3 + self.h4 + self.h5 + self.h6  # pragma: no cover

    def has_uniform_h2_or_h3(self) -> bool:
        """True si hay headings pero todos son H2 o todos son H3."""
        if self.total < 2:
            return False
        if self.h2 == self.total and self.h2 > 0:
            return True
        return bool(self.h3 == self.total and self.h3 > 0)


@dataclass(frozen=True)
class CleanerCounts:
    """Cambios por cleaner."""

    per_cleaner: dict[str, int] = field(default_factory=dict)
    total_changes: int = 0

    @classmethod
    def from_stats(
        cls, cleaner_stats: tuple[dict[str, Any], ...] | None
    ) -> CleanerCounts:
        per: dict[str, int] = {}
        total = 0
        for stat in cleaner_stats or ():
            name = str(stat.get("name", "?"))
            changes = int(stat.get("changes", 0))
            per[name] = per.get(name, 0) + changes
            total += changes
        return cls(per_cleaner=per, total_changes=total)


@dataclass(frozen=True)
class ReportStats:
    """Estadísticas de una corrida."""

    pages: int | None
    words: int
    headings: HeadingCounts
    figures: int
    cleaners: CleanerCounts
    raw_chars: int
    cleaned_chars: int
    deletion_ratio: float
    elapsed_seconds: float
    source_format: str  # "pdf" | "epub" | "docx" | "pptx" | "xlsx" | "stdin" | "other"

    def as_dict(self) -> dict[str, Any]:
        return {
            "pages": self.pages,
            "words": self.words,
            "headings": {
                "h1": self.headings.h1,
                "h2": self.headings.h2,
                "h3": self.headings.h3,
                "h4": self.headings.h4,
                "h5": self.headings.h5,
                "h6": self.headings.h6,
                "total": self.headings.total,
            },
            "figures": self.figures,
            "cleaners": {
                "per_cleaner": self.cleaners.per_cleaner,
                "total_changes": self.cleaners.total_changes,
            },
            "raw_chars": self.raw_chars,
            "cleaned_chars": self.cleaned_chars,
            "deletion_ratio": round(self.deletion_ratio, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "source_format": self.source_format,
        }


@dataclass(frozen=True)
class ReportOutput:
    """Reporte completo: stats + warnings + format."""

    schema_version: int
    stats: ReportStats
    warnings: tuple[dict[str, Any], ...]
    format: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_schema_version": self.schema_version,
            "stats": self.stats.as_dict(),
            "warnings": list(self.warnings),
            "format": self.format,
        }


# --- Heurísticas ----------------------------------------------------------


def _words_in(text: str) -> int:
    return len(WORDS_RE.findall(text or ""))


def _deletion_ratio(raw: str, cleaned: str) -> float:
    raw_len = len(raw or "")
    cleaned_len = len(cleaned or "")
    if raw_len == 0:
        return 0.0
    removed = max(0, raw_len - cleaned_len)
    return removed / raw_len


# --- collect_* -----------------------------------------------------------


def collect_stats(
    *,
    raw_markdown: str,
    final_markdown: str,
    pages: int | None,
    figures_count: int,
    cleaner_stats: tuple[dict[str, Any], ...] | None,
    elapsed_seconds: float,
    source_format: str,
) -> ReportStats:
    """Computa las stats agregadas a partir de los datos disponibles."""
    headings = HeadingCounts.from_markdown(final_markdown)
    cleaners = CleanerCounts.from_stats(cleaner_stats)
    return ReportStats(
        pages=pages,
        words=_words_in(final_markdown),
        headings=headings,
        figures=figures_count,
        cleaners=cleaners,
        raw_chars=len(raw_markdown or ""),
        cleaned_chars=len(final_markdown or ""),
        deletion_ratio=_deletion_ratio(raw_markdown, final_markdown),
        elapsed_seconds=elapsed_seconds,
        source_format=source_format,
    )


def collect_warnings(
    stats: ReportStats,
    *,
    no_clean: bool,
    format: str,
) -> list[dict[str, Any]]:
    """Devuelve la lista de heurísticas disparadas (con sugerencia)."""
    warnings: list[dict[str, Any]] = []

    pages = stats.pages or 0
    words = stats.words
    words_per_page = words / pages if pages > 0 else words

    def _add(code: str, message: str, suggestion: str) -> None:
        warnings.append(
            {"code": code, "message": message, "suggestion": suggestion}
        )

    # (a) Output vacío: hay páginas pero 0 palabras.
    if pages > 0 and words == 0:
        _add(
            "empty_output",
            f"output vacío: 0 palabras en {pages} páginas",
            (
                "verificá que el PDF tenga texto embebido; PDFs escaneados "
                "sin OCR devuelven vacío"
            ),
        )

    # (b) PDF escaneado probable: pocas palabras por página.
    if (
        format == "pdf"
        and pages >= SCANNED_MIN_PAGES
        and pages > 0
        and words_per_page < PAGE_COUNT_SCANNED_RATIO_THRESHOLD
    ):
        _add(
            "scanned_pdf",
            (
                f"PDF parece escaneado: {words} palabras en {pages} páginas"
            ),
            (
                "ejecutá OCR (ej. `ocrmypdf`) antes de pasar el archivo a capmd"
            ),
        )

    # (c) Sin headings en un PDF de >1 página.
    if (
        format == "pdf"
        and pages >= NO_HEADINGS_MIN_PAGES
        and stats.headings.total == 0
    ):
        _add(
            "no_headings",
            f"0 headings detectados en {pages} páginas",
            "revisá el modo de headings (D7); sin H1-H6 el TOC inline está vacío",
        )

    # (d) Sin figuras en un PDF grande.
    if (
        format == "pdf"
        and pages >= NO_FIGURES_MIN_PAGES
        and stats.figures == 0
        and stats.cleaners.total_changes > 0  # al menos se procesó el flujo E
    ):
        _add(
            "no_figures",
            f"0 figuras extraídas en {pages} páginas",
            (
                "revisá los filtros E5; figuras pequeñas o de fondo pueden "
                "haber sido descartadas"
            ),
        )

    # (e) Pipeline eliminó >50% del contenido (posible over-cleaning).
    if not no_clean and stats.deletion_ratio > OVER_CLEANUP_RATIO:
        pct = round(stats.deletion_ratio * 100)
        _add(
            "over_cleanup",
            f"pipeline eliminó {pct}% del contenido",
            (
                "revisá --skip-clean o pasá --only-clean a cleaners puntuales; "
                "demasiado borrado puede indicar cleaners agresivos"
            ),
        )

    # (f) Todos los headings son del mismo nivel (señal de falta de jerarquía).
    if stats.headings.has_uniform_h2_or_h3():
        level = "h2" if stats.headings.h2 == stats.headings.total else "h3"
        _add(
            "uniform_headings",
            (
                f"todos los {stats.headings.total} headings son {level.upper()}"
            ),
            (
                "verificá que el doc tenga jerarquía H1/H2 (o H2/H3); el TOC "
                "y el split funcionan mejor con estructura mixta"
            ),
        )

    return warnings


# --- Renderers -----------------------------------------------------------


def render_json(output: ReportOutput) -> str:
    """Serializa el reporte como JSON parseable (default F6)."""
    return json.dumps(
        output.as_dict(),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def render_text(output: ReportOutput) -> str:
    """Renderiza el reporte en formato human-readable con rich."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:  # rich no es dep obligatoria, fallback a texto plano.  # pragma: no cover
        return _render_text_plain(output)  # pragma: no cover

    import io

    sio = io.StringIO()
    console = Console(file=sio, force_terminal=False, color_system=None)

    console.print(Panel("[bold]capmd report (F6)[/bold]", expand=False))

    # Stats table
    table = Table(title="stats", show_header=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("pages", str(output.stats.pages))
    table.add_row("words", str(output.stats.words))
    table.add_row("headings", str(output.stats.headings.total))
    table.add_row("figures", str(output.stats.figures))
    table.add_row("cleaner_changes", str(output.stats.cleaners.total_changes))
    table.add_row("deletion_ratio", f"{output.stats.deletion_ratio:.2%}")
    table.add_row("elapsed_seconds", f"{output.stats.elapsed_seconds:.2f}s")
    table.add_row("source_format", output.stats.source_format)
    console.print(table)

    # Per-cleaner
    if output.stats.cleaners.per_cleaner:
        cleaners_table = Table(title="changes per cleaner")
        cleaners_table.add_column("name", style="bold")
        cleaners_table.add_column("changes", justify="right")
        for name, changes in output.stats.cleaners.per_cleaner.items():
            cleaners_table.add_row(name, str(changes))
        console.print(cleaners_table)

    # Warnings
    if output.warnings:
        console.print(f"[bold red]warnings ({len(output.warnings)})[/bold red]")
        for w in output.warnings:  # pragma: no cover
            console.print(
                f"  [yellow]![/yellow] {w['message']}"
            )
            console.print(f"      [dim]code: {w['code']}[/dim]")
            if w.get("suggestion"):  # pragma: no cover
                console.print(f"      [dim]→ {w['suggestion']}[/dim]")
    else:
        console.print("[green]no warnings[/green]")

    return sio.getvalue()


def _render_text_plain(output: ReportOutput) -> str:
    """Fallback sin rich: texto plano."""
    lines = [  # pragma: no cover
        "capmd report (F6)",  # pragma: no cover
        "=" * 40,  # pragma: no cover
        f"pages           : {output.stats.pages}",  # pragma: no cover
        f"words           : {output.stats.words}",  # pragma: no cover
        f"headings        : {output.stats.headings.total}",  # pragma: no cover
        f"figures         : {output.stats.figures}",  # pragma: no cover
        f"cleaner_changes : {output.stats.cleaners.total_changes}",  # pragma: no cover
        f"deletion_ratio  : {output.stats.deletion_ratio:.2%}",  # pragma: no cover
        f"elapsed_seconds : {output.stats.elapsed_seconds:.2f}s",  # pragma: no cover
        f"source_format   : {output.stats.source_format}",  # pragma: no cover
    ]  # pragma: no cover
    if output.stats.cleaners.per_cleaner:  # pragma: no cover
        lines.append("")  # pragma: no cover
        lines.append("changes per cleaner:")  # pragma: no cover
        for name, changes in output.stats.cleaners.per_cleaner.items():  # pragma: no cover
            lines.append(f"  {name:<32} {changes}")  # pragma: no cover
    if output.warnings:  # pragma: no cover
        lines.append("")  # pragma: no cover
        lines.append(f"warnings ({len(output.warnings)}):")  # pragma: no cover
        for w in output.warnings:  # pragma: no cover
            lines.append(f"  ! {w['message']}")  # pragma: no cover
            lines.append(f"      code: {w['code']}")  # pragma: no cover
            if w.get("suggestion"):  # pragma: no cover
                lines.append(f"      -> {w['suggestion']}")  # pragma: no cover
    else:  # pragma: no cover
        lines.append("")  # pragma: no cover
        lines.append("no warnings")  # pragma: no cover
    return "\n".join(lines) + "\n"  # pragma: no cover
