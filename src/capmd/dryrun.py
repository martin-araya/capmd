"""Plan dry-run (F7).

Cuando se invoca ``capmd convert --dry-run``, el flujo entero de la
conversión (markitdown, cleaners, extracción de figuras, TOC, split
planning) se ejecuta contra directorios temporales. Al final, se emite
a stdout un ``DryRunPlan`` JSON con:

  - ``input``: archivo fuente, formato, páginas, tamaño, sha256.
  - ``selection``: chapter/pages resueltos.
  - ``flags``: estado de ``--flat``, ``--split``, ``--toc``, cleaners.
  - ``output``: rutas resueltas que se hubieran escrito.
  - ``report``: ``ReportOutput`` de F6 (stats + warnings) embebido.

El filesystem del destino final queda intacto.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capmd.output.split import extract_h2_sections
from capmd.output.writer import (
    book_slug_from,
    chapter_slug_from,
)
from capmd.report import ReportOutput

__all__ = [
    "DRY_RUN_SCHEMA_VERSION",
    "DryRunPlan",
    "FlagsInfo",
    "InputInfo",
    "OutputInfo",
    "SelectionInfo",
    "build_dry_run_plan",
    "render_plan_json",
    "render_plan_text",
]


DRY_RUN_SCHEMA_VERSION = 1
_REPORT_FALLBACK_FORMAT = "json"


@dataclass(frozen=True)
class InputInfo:
    source: str
    format: str
    pages: int | None
    size_bytes: int | None
    sha256: str | None


@dataclass(frozen=True)
class SelectionInfo:
    chapter: str | None
    chapter_slug: str | None
    pages: list[int] | None
    page_offset: int


@dataclass(frozen=True)
class FlagsInfo:
    flat: bool
    split: str | None
    toc: bool
    toc_depth: int
    no_images: bool
    no_anchor: bool
    no_clean: bool
    only_clean: str | None
    skip_clean: str | None
    image_format: str


@dataclass(frozen=True)
class OutputInfo:
    requested: str | None
    kind: str  # "tree" | "flat" | "single-file" | "stdout"
    tree_files: tuple[str, ...]


@dataclass(frozen=True)
class DryRunPlan:
    dry_run: bool
    schema_version: int
    input: InputInfo
    selection: SelectionInfo
    flags: FlagsInfo
    output: OutputInfo
    report: dict[str, Any] = field(default_factory=dict)  # ReportOutput.as_dict()

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "schema_version": self.schema_version,
            "input": {
                "source": self.input.source,
                "format": self.input.format,
                "pages": self.input.pages,
                "size_bytes": self.input.size_bytes,
                "sha256": self.input.sha256,
            },
            "selection": {
                "chapter": self.selection.chapter,
                "chapter_slug": self.selection.chapter_slug,
                "pages": (
                    list(self.selection.pages)
                    if self.selection.pages is not None
                    else None
                ),
                "page_offset": self.selection.page_offset,
            },
            "flags": {
                "flat": self.flags.flat,
                "split": self.flags.split,
                "toc": self.flags.toc,
                "toc_depth": self.flags.toc_depth,
                "no_images": self.flags.no_images,
                "no_anchor": self.flags.no_anchor,
                "no_clean": self.flags.no_clean,
                "only_clean": self.flags.only_clean,
                "skip_clean": self.flags.skip_clean,
                "image_format": self.flags.image_format,
            },
            "output": {
                "requested": self.output.requested,
                "kind": self.output.kind,
                "tree_files": list(self.output.tree_files),
            },
            "report": self.report,
        }


# --- Helpers --------------------------------------------------------------


def _compute_split_tree_paths(
    *,
    out_dir_path: Path,
    book_slug: str,
    chapter_slug: str,
    final_markdown: str,
) -> list[str]:
    """Devuelve los paths que se hubieran escrito con ``--split h2``."""
    paths: list[str] = []
    chapter_dir = out_dir_path / book_slug / chapter_slug
    sections_dir = chapter_dir / "sections"
    paths.append(str(chapter_dir / f"{chapter_slug}.md"))
    paths.append(f"{chapter_dir}/images/")
    paths.append(str(chapter_dir / "capmd.json"))

    slice_ = extract_h2_sections(final_markdown)
    sections = slice_.sections
    has_prelude = bool(slice_.prelude.strip())

    if not sections and not has_prelude:
        return paths

    from capmd.output.split import (
        split_section_filenames,
    )

    filenames, intro_filename = split_section_filenames(
        sections, has_prelude=has_prelude
    )

    if intro_filename is not None:
        paths.append(str(sections_dir / intro_filename))
    for filename in filenames:
        paths.append(str(sections_dir / filename))
    paths.append(str(sections_dir / "index.md"))
    return paths


def _resolve_out_dir_path(
    requested: Path,
    source_doc_kind: str,
    stdin: bool,
    source_path: Path | None,
    resolved_chapter: Any,
    resolved_page_range: Any,
    format_for_slug: str,
) -> Path:
    """Reproduce la lógica de ``book_slug_from`` + ``build_tree_paths``."""
    class _Kind:
        def __init__(self, path: Path, fmt: str):
            self.path = path
            self.format = fmt

    if stdin or source_path is None:
        kind = _Kind(Path("stdin"), "stdin")
        book = "stdin"
    else:
        fmt = source_doc_kind or format_for_slug or "other"
        kind = _Kind(source_path, fmt)
        book = book_slug_from(kind, stdin=False)  # type: ignore[arg-type]

    chap = chapter_slug_from(
        chapter=resolved_chapter, page_range=resolved_page_range
    )
    return requested / book / chap


def _resolve_flat_path(
    requested: Path,
    stdin: bool,
    source_path: Path | None,
) -> Path:
    if stdin or source_path is None:
        return requested / "stdin.md"
    fmt = _format_from_suffix_safe(source_path.suffix)
    kind = _DocKind(source_path, fmt)
    book = book_slug_from(kind, stdin=False)  # type: ignore[arg-type]
    return requested / f"{book}.md"


def _format_from_suffix_safe(suffix: str) -> str:
    s = suffix.lower().lstrip(".")
    if s in {"pdf", "epub", "docx", "pptx", "xlsx"}:
        return s
    return "other"


class _DocKind:
    """Stand-in minimal para ``book_slug_from``. Sólo necesita ``path``
    y ``format`` (similar al dataclass ``SourceDoc``)."""

    def __init__(self, path: Path, fmt: str) -> None:
        self.path = path
        self.format = fmt


# --- Constructor principal -------------------------------------------------


def build_dry_run_plan(
    *,
    requested_out_dir: Path | None,
    requested_output: Path | None,
    flat: bool,
    split: str | None,
    toc: bool,
    toc_depth: int,
    no_images: bool,
    no_anchor: bool,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    image_format: str,
    source: str,  # filename o "<stdin>"
    source_path: Path | None,
    stdin: bool,
    source_format: str,
    pages: int | None,
    size_bytes: int | None,
    sha256: str | None,
    resolved_chapter: Any = None,
    resolved_page_range: Any = None,
    page_offset: int,
    final_markdown: str,
    report: ReportOutput | dict[str, Any] | None,
) -> DryRunPlan:
    """Arma el plan completo de la corrida.

    ``report`` puede ser un :class:`ReportOutput` (F6) o un dict ya
    serializado; en este último caso se usa tal cual.
    """
    from collections.abc import Mapping

    if isinstance(report, Mapping):
        report_dict: dict[str, Any] = dict(report)
    else:
        report_dict = report.as_dict() if report is not None else {}
    # Input
    input_info = InputInfo(
        source=source,
        format=source_format,
        pages=pages,
        size_bytes=size_bytes,
        sha256=sha256,
    )

    # Selection
    chapter_title = resolved_chapter.title if resolved_chapter is not None else None
    chapter_slug_val: str | None = None
    if resolved_chapter is not None or resolved_page_range is not None:
        chapter_slug_val = chapter_slug_from(
            chapter=resolved_chapter, page_range=resolved_page_range
        )
    pages_list: list[int] | None
    if resolved_page_range is not None:
        pages_list = list(resolved_page_range.pages)
    elif resolved_chapter is not None:
        pages_list = list(
            range(resolved_chapter.start_page, resolved_chapter.end_page)
        )
    else:
        pages_list = None
    selection = SelectionInfo(
        chapter=chapter_title,
        chapter_slug=chapter_slug_val,
        pages=pages_list,
        page_offset=page_offset,
    )

    # Flags
    flags_info = FlagsInfo(
        flat=flat,
        split=split,
        toc=toc,
        toc_depth=toc_depth,
        no_images=no_images,
        no_anchor=no_anchor,
        no_clean=no_clean,
        only_clean=only_clean,
        skip_clean=skip_clean,
        image_format=image_format,
    )

    # Output (ruta que el usuario pidió + paths concretos que se hubieran escrito)
    tree_files: tuple[str, ...] = ()
    if requested_out_dir is not None:
        requested_str = str(requested_out_dir)
        if flat:
            out_md = _resolve_flat_path(requested_out_dir, stdin, source_path)
            tree_files = (str(out_md),)
            kind = "flat"
        else:
            chapter_dir = _resolve_out_dir_path(
                requested_out_dir,
                source_format,
                stdin,
                source_path,
                resolved_chapter,
                resolved_page_range,
                source_format,
            )
            tree_files = tuple(
                _compute_split_tree_paths(
                    out_dir_path=requested_out_dir,
                    book_slug=chapter_dir.parent.name,
                    chapter_slug=chapter_dir.name,
                    final_markdown=final_markdown,
                )
            )
            kind = "tree"
    elif requested_output is not None:
        requested_str = str(requested_output)
        kind = "single-file"
        tree_files = (str(requested_output),)
    else:
        requested_str = None
        kind = "stdout"
        tree_files = ()

    output_info = OutputInfo(
        requested=requested_str,
        kind=kind,
        tree_files=tree_files,
    )

    return DryRunPlan(
        dry_run=True,
        schema_version=DRY_RUN_SCHEMA_VERSION,
        input=input_info,
        selection=selection,
        flags=flags_info,
        output=output_info,
        report=report_dict,
    )


# --- Renderers ------------------------------------------------------------


def render_plan_json(plan: DryRunPlan) -> str:
    """JSON parseable del plan (default F7)."""
    return json.dumps(
        plan.as_dict(),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def render_plan_text(plan: DryRunPlan) -> str:
    """Texto human-readable con rich (fallback plano)."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        return _render_plan_text_plain(plan)

    import io

    sio = io.StringIO()
    console = Console(file=sio, force_terminal=False, color_system=None)

    console.print(Panel("[bold]capmd dry-run (F7)[/bold]", expand=False))

    info_table = Table(title="input", show_header=False)
    info_table.add_column("key", style="bold")
    info_table.add_column("value")
    info_table.add_row("source", plan.input.source)
    info_table.add_row("format", plan.input.format)
    info_table.add_row("pages", str(plan.input.pages or "?"))
    if plan.input.size_bytes is not None:
        info_table.add_row("size_bytes", str(plan.input.size_bytes))
    if plan.input.sha256:
        info_table.add_row("sha256", plan.input.sha256[:16] + "…")
    console.print(info_table)

    sel_table = Table(title="selection", show_header=False)
    sel_table.add_column("key", style="bold")
    sel_table.add_column("value")
    sel_table.add_row("chapter", plan.selection.chapter or "—")
    sel_table.add_row("chapter_slug", plan.selection.chapter_slug or "—")
    pages = plan.selection.pages
    sel_table.add_row("pages", str(pages) if pages else "—")
    sel_table.add_row("page_offset", str(plan.selection.page_offset))
    console.print(sel_table)

    flag_table = Table(title="flags", show_header=False)
    flag_table.add_column("key", style="bold")
    flag_table.add_column("value")
    flag_table.add_row("flat", str(plan.flags.flat))
    flag_table.add_row("split", plan.flags.split or "—")
    flag_table.add_row("toc", f"{plan.flags.toc} (depth={plan.flags.toc_depth})")
    flag_table.add_row("no_images", str(plan.flags.no_images))
    flag_table.add_row("no_clean", str(plan.flags.no_clean))
    console.print(flag_table)

    out_table = Table(title="output")
    out_table.add_column("kind", style="bold")
    out_table.add_row(plan.output.kind, plan.output.requested or "(stdout)")
    if plan.output.tree_files:
        console.print(out_table)
        files_table = Table(title="would write", show_header=False)
        files_table.add_column("path")
        for fp in plan.output.tree_files:
            files_table.add_row(fp)
        console.print(files_table)
    else:
        console.print(out_table)

    if plan.report and plan.report.get("warnings"):
        console.print(
            f"[bold red]warnings ({len(plan.report['warnings'])})[/bold red]"
        )
        for w in plan.report["warnings"]:
            console.print(f"  [yellow]![/yellow] {w['message']}")
    elif plan.report:
        console.print("[green]no warnings (preview)[/green]")
    return sio.getvalue()


def _render_plan_text_plain(plan: DryRunPlan) -> str:
    lines = [
        "capmd dry-run (F7)",
        "=" * 40,
        "input:",
        f"  source     : {plan.input.source}",
        f"  format     : {plan.input.format}",
        f"  pages      : {plan.input.pages}",
        "selection:",
        f"  chapter    : {plan.selection.chapter or '—'}",
        f"  chapter_slg: {plan.selection.chapter_slug or '—'}",
        f"  pages      : {plan.selection.pages}",
        f"  offset     : {plan.selection.page_offset}",
        "flags:",
        f"  flat       : {plan.flags.flat}",
        f"  split      : {plan.flags.split}",
        f"  toc        : {plan.flags.toc} (depth={plan.flags.toc_depth})",
        "output:",
        f"  kind       : {plan.output.kind}",
        f"  requested  : {plan.output.requested}",
    ]
    if plan.output.tree_files:
        lines.append("  would write:")
        for fp in plan.output.tree_files:
            lines.append(f"    {fp}")
    if plan.report and plan.report.get("warnings"):
        lines.append(f"warnings: {len(plan.report['warnings'])}")
        for w in plan.report["warnings"]:
            lines.append(f"  ! {w['message']}")
    return "\n".join(lines) + "\n"
