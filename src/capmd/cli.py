"""CLI entry point de capmd."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from functools import wraps
from importlib import metadata
from pathlib import Path
from typing import Any, TypeVar, cast

import typer
from rich.console import Console

from capmd.convert import DEFAULT_LIMITS, ConversionLimits, Engine, parse_size
from capmd.errors import CapmdError, ConversionFailed, SourceNotFound, UnsupportedFormat
from capmd.images.filter import FilterReport
from capmd.logging import configure_logging, get_logger
from capmd.models import Figure
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


_LLM_WARNED_ONCE: bool = False


def _reset_llm_warned_once() -> None:
    """Resetea el flag singleton (uso en tests)."""
    global _LLM_WARNED_ONCE
    _LLM_WARNED_ONCE = False


def _resolve_llm_client(
    *,
    describe_images: bool,
    describe_provider: str,
    describe_model: str | None,
) -> tuple[Any, str | None]:
    """Resuelve el cliente LLM y el modelo para el Engine (E6).

    Comportamiento por flag:
      - ``describe_images=False`` → ``(None, None)``. Sin efecto.
      - ``describe_images=True``:
        - Si ``describe_provider="auto"``: detecta vía
          :func:`detect_provider_from_env`. Si no hay env var →
          warning único y ``(None, None)``.
        - Si ``describe_provider="openai"|"anthropic"|"google"`` y la
          env var correspondiente falta → warning único y ``(None, None)``.
        - Si el SDK del proveedor no está instalado → warning único
          con hint ``pip install 'capmd[llm-...]'`` y ``(None, None)``.
        - Caso feliz → ``(client_instance, model_name)``.

    Returns
    -------
    tuple[Any, str | None]
        ``(client, model)``. Si no se activa o no se puede resolver,
        ``(None, None)``.
    """
    global _LLM_WARNED_ONCE

    if not describe_images:
        return None, None

    from capmd.config import build_llm_client  # re-export from capmd.llm; tests monkeypatch this
    from capmd.llm import DEFAULT_MODELS, detect_provider_from_env

    env_by_provider: dict[str, str] = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }

    if describe_provider == "auto":
        provider = detect_provider_from_env()
        if provider is None:
            if not _LLM_WARNED_ONCE:
                logger.warning(
                    "--describe-images solicitado pero no se encontró API key "
                    "(OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY); "
                    "continuando sin descripción LLM"
                )
                _LLM_WARNED_ONCE = True
            return None, None
    else:
        provider = describe_provider
        env_var = env_by_provider.get(provider)
        if env_var is None:
            raise typer.BadParameter(
                f"--describe-provider={provider!r} no soportado "
                f"(válidos: auto, {', '.join(env_by_provider)})"
            )
        if not os.environ.get(env_var):
            if not _LLM_WARNED_ONCE:
                logger.warning(
                    "--describe-provider=%s requiere %s; continuando sin descripción",
                    provider,
                    env_var,
                )
                _LLM_WARNED_ONCE = True
            return None, None

    try:
        client = build_llm_client(provider, describe_model)
    except ImportError as exc:
        if not _LLM_WARNED_ONCE:
            logger.warning(str(exc))
            _LLM_WARNED_ONCE = True
        return None, None
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    resolved_model = describe_model or DEFAULT_MODELS.get(provider, "")
    return client, resolved_model


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
    image_format: str = typer.Option(
        "png",
        "--image-format",
        case_sensitive=False,
        help=("(E1) Formato de las imágenes extraídas del PDF: 'png' o 'webp'. Default: png."),
    ),
    image_max_width: int | None = typer.Option(
        None,
        "--image-max-width",
        min=1,
        help=(
            "(E1) Ancho máximo en píxeles para las imágenes extraídas. Si la "
            "imagen lo supera, se reescala preservando aspect ratio. "
            "Default: sin reescalado."
        ),
    ),
    filter_min_size: str | None = typer.Option(
        None,
        "--filter-min-size",
        help=(
            "(E2) Tamaño mínimo WxH en px para conservar una imagen "
            "(ej: '64x64'). Más chico → descartada. Default: 64x64."
        ),
    ),
    filter_repeat_threshold: float | None = typer.Option(
        None,
        "--filter-repeat-threshold",
        min=0.0,
        max=1.0,
        help=(
            "(E2) Fracción de páginas en que una imagen idéntica debe aparecer "
            "para ser tratada como logo repetido (0-1]. Default: 0.8."
        ),
    ),
    filter_background_coverage: float | None = typer.Option(
        None,
        "--filter-background-coverage",
        min=0.0,
        max=1.0,
        help=(
            "(E2) Cobertura mínima del bbox sobre el área de página para "
            "tratarla como fondo (0-1]. Default: 0.85."
        ),
    ),
    no_anchor: bool = typer.Option(
        False,
        "--no-anchor",
        help=(
            "(E4) No insertar ![](images/fig-CC-NN.png) en el markdown; "
            "los archivos en images/ igual se crean. Default: anclaje activo."
        ),
    ),
    page_markers: bool = typer.Option(
        False,
        "--page-markers",
        help=(
            "(D5/E4) Conservar los centinelas <!-- page N --> en el output "
            "final. Por defecto se eliminan antes de escribir el .md."
        ),
    ),
    describe_images: bool = typer.Option(
        False,
        "--describe-images",
        help=(
            "(E6) Describir imágenes embebidas vía LLM usando "
            "markitdown-ocr. Si no hay API key, continúa con un warning único."
        ),
    ),
    describe_provider: str = typer.Option(
        "auto",
        "--describe-provider",
        help=("(E6) Proveedor LLM: 'auto' (detecta desde env), 'openai', 'anthropic', 'google'."),
    ),
    describe_model: str | None = typer.Option(
        None,
        "--describe-model",
        help="(E6) Modelo a usar; si se omite, el default del proveedor.",
    ),
    no_images: bool = typer.Option(
        False,
        "--no-images",
        help=(
            "(E7) Saltar todo el bloque E (extracción, filtrado, anclaje) "
            "e insertar `<!-- figura omitida: Figura C.N -->` en la posición "
            "Y de cada imagen embebida. No se crea la carpeta images/."
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

    llm_client, llm_model = _resolve_llm_client(
        describe_images=describe_images,
        describe_provider=describe_provider,
        describe_model=describe_model,
    )
    engine = Engine(limits=limits, llm_client=llm_client, llm_model=llm_model)
    sliced_temp: Path | None = None
    extract_pages: list[int] | None = None
    chapter_index: int = 1
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
                (
                    target_path,
                    sliced_temp,
                    chapter_pages,
                ) = _resolve_chapter(path, chapter, page_offset)
                extract_pages = chapter_pages
                chapter_index = _chapter_index_from_spec(path, chapter)
                logger.info(
                    "convirtiendo %s (capítulo %r=%d, offset=%d)",
                    path,
                    chapter,
                    chapter_index,
                    page_offset,
                )
        elif pages is not None:
            target_path, sliced_temp, resolved_pages = _resolve_pages(path, pages, page_offset)
            extract_pages = resolved_pages
            logger.info(
                "convirtiendo %s (recortado con --pages, offset=%d)",
                path,
                pages,
                page_offset,
            )
        else:
            logger.info("convirtiendo %s", path)
        result = engine.convert_path(target_path)
    _report_timing(result)
    if sliced_temp is not None:
        sliced_temp.unlink(missing_ok=True)

    if source != "-":
        if not no_images:
            extraction_result = _maybe_extract_images(
                source_path=path,
                extract_pages=extract_pages,
                chapter_index=chapter_index,
                image_format=image_format,
                image_max_width=image_max_width,
                output=output,
                filter_min_size=filter_min_size,
                filter_repeat_threshold=filter_repeat_threshold,
                filter_background_coverage=filter_background_coverage,
            )
        else:
            extraction_result = None
    else:
        extraction_result = None

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

    if (
        no_images
        and source != "-"
        and path.suffix.lower() == ".pdf"
    ):
        # E7: reemplaza la pipeline de extracción+anchor por placeholders.
        final_markdown = _apply_no_images_marker(
            source_path=path,
            engine=engine,
            extract_pages=extract_pages,
            chapter_index=chapter_index,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
            keep_page_markers=page_markers,
        )
    elif not no_anchor and extraction_result is not None and extraction_result[0]:
        final_markdown = _apply_anchor(
            source_path=path,
            figures=extraction_result[0],
            engine=engine,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
            keep_page_markers=page_markers,
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


def _resolve_pages(path: Path, spec: str, offset: int = 0) -> tuple[Path, Path, list[int]]:
    """Parsea ``--pages`` contra el PDF en ``path`` y devuelve (target, temp, pages).

    ``offset`` desplaza cada número del spec antes de parsear
    (paginación impresa → física). Si la traslación lleva alguna página
    fuera del documento, ``parse_pages`` lanza ``RangeOutOfBounds`` (exit 4).

    El tercer elemento de la tupla es la lista de páginas físicas
    resueltas (1-indexed, ordenada), para que la fase E1 pueda extraer
    imágenes del PDF original sin reabrir el temp.
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
    return temp, temp, list(page_range.pages)


def _resolve_chapter(path: Path, spec: str, offset: int = 0) -> tuple[Path, Path, list[int]]:
    """Hace lookup del capítulo en el outline y devuelve (target, temp, pages).

    ``offset`` desplaza el rango resuelto del capítulo antes de slicear.
    Si la traslación lleva alguna página fuera del documento, se lanza
    ``RangeOutOfBounds`` (exit 4).

    El tercer elemento es la lista de páginas físicas (1-indexed)
    resueltas para el capítulo, que la fase E1 usa para extraer
    imágenes del PDF original.
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

    pages_list = list(range(start, end))
    page_range = PageRange(pages=tuple(pages_list))
    temp = slice_pdf(path, page_range)
    return temp, temp, pages_list


def _chapter_index_from_spec(path: Path, spec: str) -> int:
    """Resuelve el índice numérico 1-based de un spec de ``--chapter`` (E3).

    Si ``spec`` es numérico, devuelve ese entero directamente. Si no,
    resuelve contra el outline (substring case-insensitive del título)
    y devuelve ``Chapter.index``. Si el outline no existe o hay
    ambigüedad, devuelve ``1`` y loggea un warning; el nombre de las
    figuras cae al default sin romper la conversión.
    """
    spec = spec.strip()
    try:
        n = int(spec)
    except ValueError:
        n = 0
    if n >= 1:
        return n

    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        from capmd.errors import SourceNotFound
        from capmd.sources.chapters import resolve_chapter
        from capmd.sources.pdf import infer_ranges, read_outline_with_fallback

        try:
            total = len(PdfReader(str(path)).pages)
        except (FileNotFoundError, PdfReadError) as exc:
            raise SourceNotFound(
                f"no se pudo leer el PDF {path}: {exc}",
                hint="el archivo puede estar corrupto o encriptado",
            ) from exc

        chapters = read_outline_with_fallback(path)
        chapters = infer_ranges(chapters, total_pages=total)
        ch = resolve_chapter(chapters, spec)
        return ch.index
    except Exception as exc:
        logger.warning(
            "no se pudo resolver chapter_index para %r; usando 1 (%s)",
            spec,
            exc,
        )
        return 1


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


def _maybe_extract_images(
    *,
    source_path: Path,
    extract_pages: list[int] | None,
    chapter_index: int,
    image_format: str,
    image_max_width: int | None,
    output: Path | None,
    filter_min_size: str | None,
    filter_repeat_threshold: float | None,
    filter_background_coverage: float | None,
) -> tuple[list[Figure], FilterReport] | None:
    """Ejecuta E1+E2 sobre un PDF si aplica. Silencioso si no es PDF.

    Devuelve ``(figures, report)`` cuando se ejecuta; ``None`` para
    formatos no-PDF.

    Precedencia de configuración (de menor a mayor):
      defaults de FilterRules < TOML global < TOML project < CLI flags.
    La carpeta destino es sibling del ``-o`` si se pasó, o
    ``cwd/images/`` si se escribe a stdout.

    ``chapter_index`` se usa como prefijo de nombre (E3:
    ``fig-CC-NN.<ext>``); default 1 cuando no hubo ``--chapter``.
    """
    from capmd.config import load_image_filter_overrides
    from capmd.images import ExtractOptions, extract_figures
    from capmd.images.filter import FilterRules

    if source_path.suffix.lower() != ".pdf":
        return None

    fmt = image_format.lower()
    if fmt not in {"png", "webp"}:
        logger.warning(
            "--image-format=%s no es válido; se ignora la extracción",
            image_format,
        )
        return None

    rules_kwargs: dict[str, Any] = {}
    overrides = load_image_filter_overrides()
    if "min_size" in overrides:
        rules_kwargs["min_size"] = _parse_size_spec(str(overrides["min_size"]))
    for key, caster in (
        ("repeat_threshold", float),
        ("background_coverage", float),
    ):
        if key in overrides:
            try:
                rules_kwargs[key] = caster(overrides[key])
            except (TypeError, ValueError):
                logger.warning(
                    "ignorado %s=%r en TOML: no es convertible a %s",
                    key,
                    overrides[key],
                    caster.__name__,
                )

    if filter_min_size is not None:
        rules_kwargs["min_size"] = _parse_size_spec(filter_min_size)
    if filter_repeat_threshold is not None:
        rules_kwargs["repeat_threshold"] = filter_repeat_threshold
    if filter_background_coverage is not None:
        rules_kwargs["background_coverage"] = filter_background_coverage

    try:
        rules = FilterRules(**rules_kwargs)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None

    images_dir = output.parent / "images" if output is not None else Path.cwd() / "images"

    pages = extract_pages
    if pages is None:
        from pypdf import PdfReader

        try:
            total = len(PdfReader(str(source_path)).pages)
        except Exception as exc:
            raise ConversionFailed(
                f"no se pudo leer el PDF para extraer imágenes: {exc}",
                hint="el archivo puede estar corrupto o encriptado",
            ) from exc
        pages = list(range(1, total + 1))

    try:
        result = extract_figures(
            source_path,
            pages=pages,
            out_dir=images_dir,
            options=ExtractOptions(image_format=fmt, max_width=image_max_width),
            rules=rules,
            chapter_index=chapter_index,
        )
    except ValueError as exc:
        raise ConversionFailed(
            f"extracción de imágenes falló: {exc}",
            hint="revisá --image-format y --image-max-width",
        ) from exc
    except Exception as exc:
        raise ConversionFailed(
            f"extracción de imágenes falló en {source_path.name}: {exc}",
            hint="el PDF puede tener objetos embebidos no soportados",
        ) from exc

    figures = result.figures
    summary = result.report.summary()
    if figures:
        logger.info("%d figuras conservadas (%s)", len(figures), summary)
        _stderr.print(f"[dim]{summary}[/dim]")
    else:
        logger.debug("sin figuras tras filtro: %s", summary)

    return figures, result.report


def _run_cleaning_pipeline(
    raw_markdown: str,
    *,
    source_path: Path,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
) -> str:
    """Aplica el pipeline de cleaners al markdown crudo y devuelve el resultado.

    Helper interno (D1 + D15) parametrizado por la ruta usada para el
    :class:`SourceDoc`. Lo usan tanto :func:`_apply_clean_pipeline`
    (flujo normal) como :func:`_apply_anchor` (flujo E4 con page
    markers).
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

    suffix = source_path.suffix.lstrip(".").lower() or "pdf"
    format_str: str = suffix if suffix in ("pdf", "epub", "docx", "pptx", "xlsx") else "other"
    source_doc = SourceDoc(
        path=source_path,
        format=format_str,  # type: ignore[arg-type]
        sha256="0" * 64,
        size_bytes=0,
    )
    ctx = CleanContext(source=source_doc, format=format_str)  # type: ignore[arg-type]
    cleaned, _stats = pipeline.run(raw_markdown, ctx)
    return cleaned


def _apply_anchor(
    *,
    source_path: Path,
    figures: list[Figure],
    engine: Engine,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    keep_page_markers: bool,
) -> str:
    """Re-convierte por página, ancla figuras y devuelve el markdown final (E4+E5).

    Pipeline:
      1. ``engine.convert_pages(source_path)`` → lista de markdowns por página.
      2. Limpia cada página por separado (los cleaners no son estables con
         los markers porque algunos los colapsan en whitespace, etc.).
      3. Pre-pass E5: detecta captions por página y popula ``Figure.caption``.
      4. ``insert_page_markers`` re-inserta los centinelas después de limpiar.
      5. :func:`anchor_figures` inserta los ``![]()`` y, si hay caption
         cercano, también la línea italic debajo.
      6. ``strip_page_markers`` (a menos que ``keep_page_markers``).
    """
    from capmd.convert.page_markers import (
        insert_page_markers,
        strip_page_markers,
    )
    from capmd.errors import ConversionFailed
    from capmd.images.anchor import anchor_figures
    from capmd.images.extract import _collect_page_areas

    try:
        pages = engine.convert_pages(source_path)
    except Exception as exc:
        raise ConversionFailed(
            f"E4: convert_pages falló para {source_path.name}: {exc}",
            hint="probá --no-anchor para usar el flujo sin anclaje",
        ) from exc

    if not pages:
        return ""

    # Limpiar por página para preservar los markers.
    cleaned_pages: list[str] = [
        _run_cleaning_pipeline(
            page_text,
            source_path=source_path,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
        )
        for page_text in pages
    ]

    page_areas = _collect_page_areas(source_path, list(range(1, len(cleaned_pages) + 1)))

    # E5: pre-pass para poblar Figure.caption.
    _attribute_captions_by_page(figures, cleaned_pages, page_areas)

    md_with_markers = insert_page_markers(cleaned_pages)
    anchored = anchor_figures(
        md_with_markers,
        figures,
        page_areas=page_areas,
        relative_path_prefix="images/",
    )
    return anchored if keep_page_markers else strip_page_markers(anchored)


def _apply_no_images_marker(
    *,
    source_path: Path,
    engine: Engine,
    extract_pages: list[int] | None,
    chapter_index: int,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    keep_page_markers: bool,
) -> str:
    """Salta extracción y anclaje (E7 ``--no-images``) e inserta placeholders.

    Pipeline:
      1. ``engine.convert_pages(source_path)`` → markdowns por página.
      2. Limpia cada página por separado (los cleaners no son estables
         con los centinelas insertados en medio del texto).
      3. :func:`extract_figure_placeholders` (sin escribir PNG) →
         lista de :class:`FigurePlaceholder` por página.
      4. ``insert_page_markers`` re-inserta los centinelas.
      5. :func:`insert_image_placeholders` inserta ``<!-- figura omitida: … -->``
         en la posición Y de cada placeholder.
      6. ``strip_page_markers`` (a menos que ``keep_page_markers``).

    Si el PDF no tiene imágenes, devuelve el markdown sin placeholders.
    """
    from capmd.convert.page_markers import (
        insert_page_markers,
        strip_page_markers,
    )
    from capmd.errors import ConversionFailed
    from capmd.images.anchor import (
        extract_figure_placeholders,
        insert_image_placeholders,
    )
    from capmd.images.extract import _collect_page_areas

    try:
        pages = engine.convert_pages(source_path)
    except Exception as exc:
        raise ConversionFailed(
            f"E7: convert_pages falló para {source_path.name}: {exc}",
            hint="probá sin --no-images",
        ) from exc

    if not pages:
        return ""

    cleaned_pages: list[str] = [
        _run_cleaning_pipeline(
            page_text,
            source_path=source_path,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
        )
        for page_text in pages
    ]

    page_areas = _collect_page_areas(source_path, list(range(1, len(cleaned_pages) + 1)))
    placeholders = extract_figure_placeholders(
        source_path,
        pages=list(range(1, len(cleaned_pages) + 1)),
        chapter_index=chapter_index,
        page_areas=page_areas,
    )

    md_with_markers = insert_page_markers(cleaned_pages)
    md_with_placeholders = insert_image_placeholders(md_with_markers, placeholders)
    return md_with_placeholders if keep_page_markers else strip_page_markers(
        md_with_placeholders
    )


def _attribute_captions_by_page(
    figures: list[Figure],
    cleaned_pages: list[str],
    page_areas: Mapping[int, tuple[float, float]],
) -> None:
    """Popula ``Figure.caption`` para cada figura a partir del markdown (E5).

    Recorre cada página; para cada figura de esa página, ordenada por
    ``y_frac``, busca un caption en la ventana de 3 líneas empezando
    desde la posición del anchor esperado (basado en y_frac). Si el
    número del caption (``chapter.figure``) coincide con el de la
    figura, lo popula; si no, usa el siguiente caption posicional
    como fallback.
    """
    from capmd.images.anchor import _y_fraction
    from capmd.images.captions import find_caption_in_window

    # Map: page → list[Figure]
    figures_by_page: dict[int, list[Figure]] = {}
    for fig in figures:
        if fig.page >= 1:
            figures_by_page.setdefault(fig.page, []).append(fig)

    for page_num, page_figs in figures_by_page.items():
        page_idx = page_num - 1
        if not (0 <= page_idx < len(cleaned_pages)):
            continue
        page_lines = cleaned_pages[page_idx].splitlines()

        page_height = 1.0
        area = page_areas.get(page_num)
        if area is not None:
            _pw, page_height = area

        ordered = sorted(
            page_figs,
            key=lambda fig: _y_fraction(fig, page_height) or 1.0,
        )

        # Construir mapping de "target line" para cada figura para no
        # re-iterar; reusar el mismo cálculo de target que anchor.
        cursor = 0
        non_empty_idx = [i for i, ln in enumerate(page_lines) if ln.strip()]
        n = len(non_empty_idx)

        for fig in ordered:
            y_frac = _y_fraction(fig, page_height)
            if y_frac is None or n == 0:
                target = len(page_lines)
            else:
                if y_frac == 0.0:
                    target = 0
                elif y_frac >= 1.0:
                    target = len(page_lines)
                else:
                    target_idx = int(y_frac * n)
                    target_idx = min(target_idx, n - 1)
                    target = non_empty_idx[target_idx] + 1

            caption = find_caption_in_window(page_lines, target, window=3)
            if caption is not None:
                # Numérico-match: caption.ref == "chapter.figure" de la figura.
                expected_ref = f"{fig.chapter_index}.{fig.index}"
                if caption.ref == expected_ref or cursor >= len(page_lines):
                    object.__setattr__(fig, "caption", caption.raw)
                    cursor = max(cursor, caption.line_index + 1)
                else:
                    # Fallback posicional: tomar el siguiente caption disponible.
                    object.__setattr__(fig, "caption", caption.raw)
                    cursor = caption.line_index + 1
            else:
                # Sin caption: avanzar el cursor al target para no reusarlo.
                cursor = max(cursor, target)
            # ``cursor`` ya no se incrementa más allá del último caption
            # encontrado, pero ``find_caption_in_window`` consume solo una
            # línea por llamada.


def _parse_size_spec(spec: str) -> tuple[int, int]:
    """Parsea 'WxH' o 'W,H' a ``(W, H)``. Levanta ``ValueError`` si malformado."""
    cleaned = spec.strip().lower().replace("x", ",")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"spec de tamaño inválido {spec!r}: se esperaba 'WxH' (ej: '64x64')")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"spec de tamaño no numérico {spec!r}") from exc
    if w <= 0 or h <= 0:
        raise ValueError(f"spec de tamaño debe ser > 0, recibido {spec!r}")
    return (w, h)


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
    ``CleanContext`` mínimo a partir de la ruta de salida. Wrapper
    sobre :func:`_run_cleaning_pipeline` para mantener el contrato
    existente.
    """
    return _run_cleaning_pipeline(
        raw_markdown,
        source_path=target_path,
        no_clean=no_clean,
        only_clean=only_clean,
        skip_clean=skip_clean,
    )


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
