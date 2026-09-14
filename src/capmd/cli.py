"""CLI entry point de capmd."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import wraps
from importlib import metadata
from pathlib import Path
from typing import Any, TypeVar, cast

import typer
from rich.console import Console

from capmd.convert import DEFAULT_LIMITS, ConversionLimits, Engine, parse_size
from capmd.errors import CapmdError, SourceNotFound, UnsupportedFormat
from capmd.logging import configure_logging, get_logger
from capmd.output.snapshot import write_raw_snapshot

_F = TypeVar("_F", bound=Callable[..., Any])

logger = get_logger(__name__)

_stderr = Console(stderr=True, soft_wrap=True)


def _handle_capmd_errors(func: _F) -> _F:
    """Captura CapmdError en el comando, renderiza con rich y sale con exit_code.

    Necesario porque CliRunner.invoke no pasa por `Typer.__call__`, sino por
    `click_command.main()` directo. El decorador cubre ambos paths.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except CapmdError as e:
            _render_error(e)
            raise typer.Exit(code=e.exit_code) from None

    return cast(_F, wrapper)


def _render_error(e: CapmdError) -> None:
    """Imprime un CapmdError con rich a stderr (regla 4 de agent.md)."""
    console = Console(stderr=True)
    console.print(f"[bold red]Error:[/bold red] {e.message}")
    if e.hint:
        console.print(f"[dim]Sugerencia:[/dim] {e.hint}")


def _resolve_version() -> str:
    """Lee la versión instalada vía importlib.metadata; cae al literal si falla."""
    try:
        return metadata.version("capmd")
    except metadata.PackageNotFoundError:
        from capmd import __version__

        return __version__


app = typer.Typer(
    name="capmd",
    help="Recorta el capítulo de un libro y lo deja en Markdown limpio.",
    add_completion=False,
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def _root(
    ctx: typer.Context,
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help="Aumenta el nivel de detalle. -v = INFO, -vv = DEBUG.",
    ),
) -> None:
    """Stub root callback. Logging configurado por verbose count."""
    configure_logging(verbose)
    logger.debug("capmd CLI iniciando (verbose=%d)", verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)


@app.command()
def version() -> None:
    """Imprime la versión de capmd."""
    typer.echo(f"capmd {_resolve_version()}")


@app.command()
@_handle_capmd_errors
def convert(
    source: str = typer.Argument(
        ...,
        help=(
            "Archivo a convertir (PDF, EPUB, DOCX, PPTX, XLSX). "
            "Pasá '-' para leer desde stdin; en ese caso --ext es obligatorio."
        ),
    ),
    ext: str | None = typer.Option(
        None,
        "--ext",
        case_sensitive=False,
        help=(
            "Formato del contenido leído por stdin. Obligatorio cuando "
            "source es '-'. Ejemplos: pdf, docx, pptx."
        ),
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "-o",
        "--output",
        help="Archivo de salida (.md). Si se omite, escribe a stdout.",
    ),
    max_size: str | None = typer.Option(
        None,
        "--max-size",
        help=("Tamaño máximo del archivo (B5). Acepta sufijos K/M/G (decimales). Default: 500M."),
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="Cantidad máxima de páginas (B5). Default: 5000.",
        min=1,
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Tiempo máximo de la conversión en segundos (B5). Default: 600.",
        min=1,
    ),
    warn_pages: int | None = typer.Option(
        None,
        "--warn-pages",
        help="Umbral para avisar por stderr si el PDF tiene más páginas (B5). Default: 500.",
        min=1,
    ),
    keep_raw: bool = typer.Option(
        False,
        "--keep-raw",
        help=(
            "Guarda el markdown crudo (pre-limpieza) en "
            "<dir>/.capmd/raw.md para diffear contra el output final "
            "(B6). Default: no se guarda."
        ),
    ),
    no_clean: bool = typer.Option(
        False,
        "--no-clean",
        help=(
            "Salta todos los cleaners. El output es byte-a-byte el markdown "
            "crudo del engine. Equivalente a --keep-raw sin guardar snapshot."
        ),
    ),
    only_clean: str | None = typer.Option(
        None,
        "--only-clean",
        help=(
            "Lista separada por comas de cleaners a ejecutar (ej: 'headers,hyphens'). "
            "Mutuamente excluyente con --skip-clean. Default: todos."
        ),
    ),
    skip_clean: str | None = typer.Option(
        None,
        "--skip-clean",
        help=(
            "Lista separada por comas de cleaners a saltar (ej: 'tables'). "
            "Mutuamente excluyente con --only-clean. Default: ninguno."
        ),
    ),
    pages: str | None = typer.Option(
        None,
        "--pages",
        help=(
            "Páginas a convertir (solo PDF). Sintaxis: '45-78', '45-' "
            "(hasta el final), '-30' (desde 1), '12,15,20-25'. "
            "Incompatible con stdin y --chapter."
        ),
    ),
    chapter: str | None = typer.Option(
        None,
        "--chapter",
        help=(
            "Capítulo por índice numérico (1-based, incluye sub-entradas) "
            "o por substring case-insensitive del título. "
            "Ej: --chapter 3, --chapter 'Ownership'. "
            "Incompatible con --pages y stdin."
        ),
    ),
    page_offset: int = typer.Option(
        0,
        "--page-offset",
        help=(
            "Diferencia entre paginación impresa y física (printed - physical). "
            "Aplica a --pages y al rango del --chapter. Negativo para libros "
            "con front matter en romanos. Default: 0."
        ),
    ),
) -> None:
    """Convierte un archivo a Markdown vía markitdown."""
    try:
        limits = _build_limits(max_size, max_pages, timeout, warn_pages)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    if chapter is not None and pages is not None:
        raise typer.BadParameter("--chapter y --pages son mutuamente excluyentes")

    only_clean_str = only_clean if isinstance(only_clean, str) else None
    skip_clean_str = skip_clean if isinstance(skip_clean, str) else None
    if only_clean_str and skip_clean_str:
        raise typer.BadParameter("--only-clean y --skip-clean son mutuamente excluyentes")

    # EPUB no soporta --pages ni --page-offset (no hay paginación física).
    # Validamos temprano para fallar con mensaje claro antes de abrir el archivo.
    source_path = Path(source)
    is_epub = source_path.suffix.lower() == ".epub" if source != "-" else False
    if is_epub:
        if pages is not None:
            raise typer.BadParameter("--pages no aplica a EPUB; usá --chapter")
        if page_offset != 0:
            raise typer.BadParameter("--page-offset no aplica a EPUB (no hay paginación física)")

    engine = Engine(limits=limits)
    sliced_temp: Path | None = None
    if source == "-":
        if ext is None:
            raise UnsupportedFormat(
                "falta --ext para leer desde stdin",
                hint="indicá el formato: capmd convert - --ext pdf",
            )
        if pages is not None:
            raise typer.BadParameter(
                "--pages no se puede combinar con stdin (pasá la ruta directa)"
            )
        if chapter is not None:
            raise typer.BadParameter(
                "--chapter no se puede combinar con stdin (pasá la ruta directa)"
            )
        if sys.stdin.isatty():
            raise SourceNotFound(
                "no hay datos en stdin",
                hint="pipeá un archivo (cat x.pdf | capmd convert - --ext pdf) "
                "o pasá la ruta directa",
            )
        logger.info("convirtiendo stdin como %s", ext)
        result = engine.convert_stream(sys.stdin.buffer, extension=ext)
    else:
        path = Path(source)
        if not path.exists() or not path.is_file():
            raise SourceNotFound(
                f"no se encontró el archivo: {path}",
                hint="verificá la ruta o pasá el archivo por stdin con --ext",
            )
        target_path = path
        if chapter is not None:
            if path.suffix.lower() == ".epub":
                target_path, sliced_temp = _resolve_chapter_epub(path, chapter)
                logger.info("convirtiendo %s (capítulo %r)", path, chapter)
            else:
                target_path, sliced_temp = _resolve_chapter(path, chapter, page_offset)
                logger.info(
                    "convirtiendo %s (capítulo %r, offset=%d)",
                    path,
                    chapter,
                    page_offset,
                )
        elif pages is not None:
            target_path, sliced_temp = _resolve_pages(path, pages, page_offset)
            logger.info(
                "convirtiendo %s (recortado con --pages, offset=%d)",
                path,
                page_offset,
            )
        else:
            logger.info("convirtiendo %s", path)
        result = engine.convert_path(target_path)
    _report_timing(result)
    if sliced_temp is not None:
        sliced_temp.unlink(missing_ok=True)

    raw_markdown = result.markdown
    if source == "-":
        final_markdown = _apply_clean_pipeline_to_stdin(
            raw_markdown,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
            ext=ext or "other",
        )
    else:
        final_markdown = _apply_clean_pipeline(
            raw_markdown,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
            target_path=target_path,
        )

    if keep_raw:
        snapshot_path = write_raw_snapshot(raw_markdown, output_path=output)
        logger.info("snapshot crudo: %s", snapshot_path)
        _stderr.print(f"[dim]snapshot crudo: {snapshot_path}[/dim]")
    if output is None:
        typer.echo(final_markdown)
        return
    output.write_text(final_markdown, encoding="utf-8")
    logger.debug("escrito %d chars a %s", len(final_markdown), output)


def _resolve_pages(path: Path, spec: str, offset: int = 0) -> tuple[Path, Path]:
    """Parsea ``--pages`` contra el PDF en ``path`` y devuelve (target, temp).

    ``offset`` desplaza cada número del spec antes de parsear
    (paginación impresa → física). Si la traslación lleva alguna página
    fuera del documento, ``parse_pages`` lanza ``RangeOutOfBounds`` (exit 4).
    """
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    from capmd.errors import SourceNotFound
    from capmd.sources.pages import parse_pages, translate_spec
    from capmd.sources.pdf import slice_pdf

    try:
        total = len(PdfReader(str(path)).pages)
    except (FileNotFoundError, PdfReadError) as exc:
        raise SourceNotFound(
            f"no se pudo leer el PDF {path}: {exc}",
            hint="el archivo puede estar corrupto o encriptado",
        ) from exc

    spec_for_parser = translate_spec(spec, offset=offset)
    try:
        page_range = parse_pages(spec_for_parser, total_pages=total)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    temp = slice_pdf(path, page_range)
    return temp, temp


def _resolve_chapter(path: Path, spec: str, offset: int = 0) -> tuple[Path, Path]:
    """Hace lookup del capítulo en el outline y devuelve (target, temp).

    ``offset`` desplaza el rango resuelto del capítulo antes de slicear.
    Si la traslación lleva alguna página fuera del documento, se lanza
    ``RangeOutOfBounds`` (exit 4).
    """
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    from capmd.errors import RangeOutOfBounds, SourceNotFound
    from capmd.models import PageRange
    from capmd.sources.chapters import resolve_chapter
    from capmd.sources.pdf import infer_ranges, read_outline_with_fallback, slice_pdf

    try:
        total = len(PdfReader(str(path)).pages)
    except (FileNotFoundError, PdfReadError) as exc:
        raise SourceNotFound(
            f"no se pudo leer el PDF {path}: {exc}",
            hint="el archivo puede estar corrupto o encriptado",
        ) from exc

    chapters = read_outline_with_fallback(path)
    chapters = infer_ranges(chapters, total_pages=total)
    try:
        ch = resolve_chapter(chapters, spec)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    start = ch.start_page + offset
    end = ch.end_page + offset
    if start > total or end > total + 1:
        last_inclusive = end - 1
        raise RangeOutOfBounds(
            f"offset {offset:+d} lleva el capítulo a páginas {start}-{last_inclusive}, "
            f"fuera del documento ({total} físicas)",
            hint="revisá --page-offset o usá --pages para controlar el rango",
        )

    page_range = PageRange(pages=tuple(range(start, end)))
    temp = slice_pdf(path, page_range)
    return temp, temp


def _resolve_chapter_epub(path: Path, spec: str) -> tuple[Path, Path]:
    """Versión EPUB de :func:`_resolve_chapter`.

    El EPUB no tiene paginación física, así que no hay offset. El XHTML
    del capítulo se extrae a un archivo ``.xhtml`` temporal que
    ``markitdown`` pueda convertir.
    """
    from capmd.sources.chapters import resolve_chapter
    from capmd.sources.epub import read_outline as read_outline_epub
    from capmd.sources.epub import slice_epub

    chapters = read_outline_epub(path)
    try:
        ch = resolve_chapter(chapters, spec)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    temp = slice_epub(path, ch)
    return temp, temp


def _build_limits(
    max_size: str | None,
    max_pages: int | None,
    timeout: int | None,
    warn_pages: int | None,
) -> ConversionLimits:
    """Arma el :class:`ConversionLimits` a partir de los flags del CLI.

    Si un flag es ``None``, mantiene el default de ``ConversionLimits``.
    ``max_size`` se parsea con :func:`parse_size`; un valor inválido
    levanta ``ValueError`` que el caller convierte en ``typer.BadParameter``.
    """
    size_bytes = parse_size(max_size) if max_size is not None else DEFAULT_LIMITS.max_size_bytes
    return ConversionLimits(
        max_size_bytes=size_bytes,
        max_pages=max_pages if max_pages is not None else DEFAULT_LIMITS.max_pages,
        timeout_seconds=(timeout if timeout is not None else DEFAULT_LIMITS.timeout_seconds),
        warn_pages=(warn_pages if warn_pages is not None else DEFAULT_LIMITS.warn_pages),
    )


def _report_timing(result: Any) -> None:
    """Imprime una línea de stats a stderr con rich (regla 4 de agent.md)."""
    parts = [f"convertido en {result.elapsed_seconds:.2f}s"]
    if result.page_count is not None:
        parts.append(f"{result.page_count} páginas")
    if result.size_bytes is not None:
        mb = result.size_bytes / 1_000_000
        parts.append(f"{mb:.1f} MB")
    _stderr.print(f"[dim]{' · '.join(parts)}[/dim]")


def _parse_clean_list(spec: str | None) -> tuple[str, ...]:
    """Parsea una lista separada por comas a tupla de nombres trimmed."""
    if not spec:
        return ()
    return tuple(s.strip() for s in spec.split(",") if s.strip())


def _apply_clean_pipeline(
    raw_markdown: str,
    *,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    target_path: Path,
) -> str:
    """Aplica el pipeline de cleaners al markdown crudo.

    ``--no-clean`` devuelve el input intacto. ``--only-clean`` y
    ``--skip-clean`` filtran el pipeline por defecto. Construye un
    ``CleanContext`` mínimo a partir de la ruta de salida.
    """
    if no_clean:
        return raw_markdown

    from capmd.clean.context import CleanContext
    from capmd.clean.pipeline import default_pipeline, filter_pipeline
    from capmd.models import SourceDoc

    pipeline = default_pipeline()
    try:
        pipeline = filter_pipeline(
            pipeline,
            only=_parse_clean_list(only_clean),
            skip=_parse_clean_list(skip_clean),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    suffix = target_path.suffix.lstrip(".").lower() or "pdf"
    format_str: str = suffix if suffix in ("pdf", "epub", "docx", "pptx", "xlsx") else "other"
    source_doc = SourceDoc(
        path=target_path,
        format=format_str,  # type: ignore[arg-type]
        sha256="0" * 64,
        size_bytes=0,
    )
    ctx = CleanContext(source=source_doc, format=format_str)  # type: ignore[arg-type]
    final_markdown, _stats = pipeline.run(raw_markdown, ctx)
    return final_markdown


def _apply_clean_pipeline_to_stdin(
    raw_markdown: str,
    *,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    ext: str,
) -> str:
    """Variante para stdin: usa un path placeholder en ``SourceDoc``."""
    if no_clean:
        return raw_markdown

    from capmd.clean.context import CleanContext
    from capmd.clean.pipeline import default_pipeline, filter_pipeline
    from capmd.models import SourceDoc

    pipeline = default_pipeline()
    try:
        pipeline = filter_pipeline(
            pipeline,
            only=_parse_clean_list(only_clean),
            skip=_parse_clean_list(skip_clean),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    format_str: str = ext if ext in ("pdf", "epub", "docx", "pptx", "xlsx") else "other"
    placeholder_path = Path(f"<stdin>.{ext}")
    source_doc = SourceDoc(
        path=placeholder_path,
        format=format_str,  # type: ignore[arg-type]
        sha256="0" * 64,
        size_bytes=0,
    )
    ctx = CleanContext(source=source_doc, format=format_str)  # type: ignore[arg-type]
    final_markdown, _stats = pipeline.run(raw_markdown, ctx)
    return final_markdown


@app.command(name="toc")
@_handle_capmd_errors
def toc(
    source: Path = typer.Argument(  # noqa: B008
        ...,
        help="PDF o EPUB del cual imprimir el outline (índice).",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Salida machine-readable en JSON a stdout (en vez del árbol rich).",
    ),
) -> None:
    """Imprime el índice (TOC) del archivo en forma de árbol o JSON."""
    import json

    from capmd.cli_render import chapters_to_json_dict, render_outline_tree
    from capmd.errors import SourceNotFound
    from capmd.sources.pdf import infer_ranges, read_outline_with_fallback

    if source.suffix.lower() == ".epub":
        from capmd.sources.epub import read_outline as read_outline_epub

        chapters = read_outline_epub(source)
        total_pages = len(chapters)
    else:
        chapters = read_outline_with_fallback(source)
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(source))
            total_pages = len(reader.pages)
        except Exception as exc:
            raise SourceNotFound(
                f"no se pudo abrir el PDF para contar páginas: {exc}",
                hint="el archivo puede estar corrupto o encriptado",
            ) from exc
        chapters = infer_ranges(chapters, total_pages=total_pages)

    if json_output:
        payload = chapters_to_json_dict(source, chapters, total_pages=total_pages)
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    tree = render_outline_tree(source, chapters)
    Console().print(tree)
