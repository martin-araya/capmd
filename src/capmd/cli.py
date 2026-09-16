"""CLI entry point de capmd."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from functools import wraps
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

import typer
from rich.console import Console

from capmd import registry as _registry_mod
from capmd.clean.cleaner import CleanerStat
from capmd.convert import DEFAULT_LIMITS, ConversionLimits, Engine, parse_size
from capmd.errors import CapmdError, ConversionFailed, SourceNotFound, UnsupportedFormat
from capmd.images.filter import FilterReport
from capmd.logging import configure_logging, configure_quiet, get_logger
from capmd.models import Chapter, Figure, PageRange, SourceDoc
from capmd.output.snapshot import write_raw_snapshot
from capmd.output.writer import OutputPaths
from capmd.progress import silent_console_text_io, stages
from capmd.registry import BookRecord, lookup_toc, upsert_book
from capmd.sources.chapters import parse_chapters_spec as _parse_chapters_spec

_F = TypeVar("_F", bound=Callable[..., Any])

logger = get_logger(__name__)

_stderr = Console(stderr=True, soft_wrap=True)


def _silence_stderr(quiet: bool) -> None:
    """Redirige ``_stderr`` a un buffer vacío cuando ``--quiet`` está activo.

    Mantiene la misma instancia de ``Console`` (los call sites usan el
    global) pero cambia su ``file`` a un ``StringIO``. Al volver a
    ``False``, restaura ``sys.stderr``.
    """
    if quiet:
        _stderr.file = silent_console_text_io()
    else:
        _stderr.file = sys.stderr


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
    add_completion=True,
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
)


config_app = typer.Typer(
    name="config",
    help="Inicializa o inspecciona el TOML de configuración (G4).",
    no_args_is_help=True,
)
app.add_typer(config_app)


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
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        is_flag=True,
        help=(
            "(H1) Suprime progreso, logs y el F6 report. stderr queda "
            "vacío al final de una corrida exitosa. Gana sobre --verbose."
        ),
    ),
) -> None:
    """Stub root callback. Logging configurado por verbose count + --quiet."""
    configure_logging(verbose)
    if quiet:
        configure_quiet()
    logger.debug("capmd CLI iniciando (verbose=%d, quiet=%s)", verbose, quiet)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    _silence_stderr(quiet)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)


@app.command()
def version() -> None:
    """Imprime la versión de capmd."""
    typer.echo(f"capmd {_resolve_version()}")


@app.command(name="open")
@_handle_capmd_errors
def open_(
    ctx: typer.Context,
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Archivo a abrir (.md u otro).",
    ),
    editor: str | None = typer.Option(
        None,
        "--editor",
        help=(
            "Override del comando editor. Si no, usa ``$EDITOR`` (o "
            "``open`` en macOS). Acepta shell words: ``code --wait``."
        ),
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", is_flag=True,
        help="(H1) Silencia el log a stderr (no afecta al open).",
    ),
) -> None:
    """Abre un archivo en el editor (``$EDITOR`` o ``open`` en macOS) (H5)."""
    from capmd.open import open_in_editor

    quiet_effective = quiet or bool(
        ctx.obj.get("quiet", False) if ctx is not None else False
    )

    try:
        open_in_editor(path, editor=editor)
    except FileNotFoundError as exc:
        raise typer.BadParameter(
            f"editor no encontrado ({exc.filename or exc.strerror}). "
            "Verificá $EDITOR o --editor."
        ) from None
    except typer.BadParameter:
        raise

    if not quiet_effective:
        typer.echo(f"abierto: {path}", err=True)


@app.command()
@_handle_capmd_errors
def convert(
    ctx: typer.Context,  # typer auto-inject; tests directos pasan kwargs por nombre.
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
    out_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--out",
        help=(
            "(F1) Directorio padre del árbol de salida. Crea "
            "<DIR>/<book-slug>/<chapter-slug>/{file.md, images/, capmd.json}. "
            "Mutuamente excluyente con -o/--output. Sin este flag se escribe "
            "a -o o stdout."
        ),
    ),
    flat: bool = typer.Option(
        False,
        "--flat",
        help=(
            "(F1) Con --out, escribe solo <DIR>/<book-slug>.md. Sin images/, "
            "sin capmd.json, sin extracción de imágenes. Sin --out es error."
        ),
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
            "con front matter en romanos. Default: 0 (o el del TOML / env)."
        ),
    ),
    image_format: str = typer.Option(
        "png",
        "--image-format",
        case_sensitive=False,
        help=(
            "(E1) Formato de las imágenes extraídas del PDF: 'png' o 'webp'. "
            "Default: 'png' (o el del TOML / env)."
        ),
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
    open_after: bool = typer.Option(
        False,
        "--open",
        is_flag=True,
        help=(
            "(H5) Tras escribir el .md, abrirlo en $EDITOR (o `open` en "
            "macOS). Fire-and-forget: no espera al editor."
        ),
    ),
    open_cmd: str | None = typer.Option(
        None,
        "--open-cmd",
        help=(
            "(H5) Override del comando editor para ``--open``. Si no, "
            "usa ``$EDITOR`` (o ``open`` en macOS). Acepta shell words, "
            "ej: ``code --wait``."
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
    split: str | None = typer.Option(
        None,
        "--split",
        case_sensitive=False,
        help=(
            "(F4) Además del chapter .md, partir por secciones H2 en una "
            "subcarpeta `sections/` con un archivo por H2 + un `index.md`. "
            "F4 acepta solo 'h2'. Requiere --out (incompatible con --flat "
            "y con -o/--output)."
        ),
    ),
    toc: bool = typer.Option(
        False,
        "--toc",
        help=(
            "(F5) Insertar tabla de contenidos al inicio del .md "
            "(después del primer H1, o al tope del body si no hay H1). "
            "Con --split, solo se inyecta en el chapter .md raíz, no "
            "en las secciones."
        ),
    ),
    toc_depth: int = typer.Option(
        3,
        "--toc-depth",
        min=2,
        max=6,
        help="(F5) Nivel máximo de headings a incluir en la TOC. Default: 3 (H2+H3).",
    ),
    report_format: str = typer.Option(
        "json",
        "--report-format",
        case_sensitive=False,
        help=(
            "(F6) Formato del reporte de calidad al final de la corrida. "
            "'json' (default, parseable) o 'text' (human-readable)."
        ),
    ),
    no_warnings: bool = typer.Option(
        False,
        "--no-warnings",
        help="(F6) Imprime el reporte sin la sección de warnings.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "(F6) Si hay warnings, exit code 8 en lugar de 0. Útil en CI."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "(F7) Corre toda la conversión contra un directorio temporal; "
            "no escribe archivos al destino. Emite a stdout un plan "
            "(JSON por default) con input + rango + output + F6 report."
        ),
    ),
    dry_run_format: str = typer.Option(
        "json",
        "--dry-run-format",
        case_sensitive=False,
        help="(F7) Formato del plan: 'json' (default, parseable) o 'text' (human).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "(F8) Si el destino existe, lo borra y reescribe desde cero. "
            "Destructivo: archivos no generados por capmd en el destino "
            "se pierden."
        ),
    ),
    suffix: bool = typer.Option(
        False,
        "--suffix",
        help=(
            "(F8) Si el destino existe, versiona con sufijo numérico "
            "'-1', '-2', ... en lugar de sobrescribir. Mutuamente "
            "excluyente con --force."
        ),
    ),
    book: str | None = typer.Option(
        None,
        "--book",
        help=(
            "(G3) Activa un perfil declarado en [books.\"<id>\"] del "
            "TOML (project > global). Sin este flag, se intenta "
            "auto-matching por sha256 del PDF contra perfiles "
            "[books.\"sha256:<hash>\"]."
        ),
    ),
    no_registry: bool = typer.Option(
        False,
        "--no-registry",
        help=(
            "(G5) No leer ni escribir el registry local de libros "
            "(~/.config/capmd/registry.json). Útil para CI, runs de "
            "una sola vez, o cuando querés forzar re-parseo del outline."
        ),
    ),
) -> None:
    """Convierte un archivo a Markdown vía markitdown."""
    try:
        limits = _build_limits(max_size, max_pages, timeout, warn_pages)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    # G2: aplicar defaults con precedencia CLI > env > project > global > defaults.
    # Se ejecuta SOLO cuando ``ctx`` está disponible (camino Typer/Click).
    # En llamadas directas a ``convert()`` desde tests se omite, ya que
    # ``out_dir``/``flat`` llegan como ``typer.Option`` puros y la
    # sustitución rompería validaciones que dependen del sentinel.

    from capmd import config as _capmd_config

    # Sentinels fuera del ``if`` para que mypy no se queje de flujo
    # condicional. En el camino ``ctx is None`` (tests directos) no
    # se usan: el perfil queda ``None`` y nada se reemplaza.
    _cfg: _capmd_config.CapmdConfig | None = None
    _book_profile: _capmd_config.BookProfile | None = None
    _title_pattern: str | None = None

    if ctx is not None:
        _cfg = _capmd_config.load_config()

        def _is_commandline(flag_name: str) -> bool:
            try:
                src = ctx.get_parameter_source(flag_name)
            except Exception:
                return False
            if src is None:
                return False
            # ``typer.Context`` usa su propio enum ``ParameterSource``
            # (typer._click.core). Comparar por ``.name`` evita la
            # dependencia de identidad de clase.
            return getattr(src, "name", "") == "COMMANDLINE"

        def _from_cfg(attr: str, current: object, *, flag_name: str) -> object:
            # Si el flag fue pasado por CLI, gana (incluso si su valor
            # coincide con el default — `ParameterSource` nos dice si
            # fue explícito).
            if _is_commandline(flag_name):
                return current
            return getattr(_cfg, attr)

        from typing import cast
        out_dir = cast(Path | None, _from_cfg("out_dir", out_dir, flag_name="out_dir"))
        page_offset = cast(int, _from_cfg("page_offset", page_offset, flag_name="page_offset"))
        image_format = cast(str, _from_cfg("image_format", image_format, flag_name="image_format"))
        if not _is_commandline("only_clean") and _cfg.cleaners_enabled is not None:
            only_clean = ",".join(_cfg.cleaners_enabled)
        if not _is_commandline("skip_clean") and _cfg.cleaners_disabled is not None:
            skip_clean = ",".join(_cfg.cleaners_disabled)

        # G3: nombre del perfil de libro (--book). El auto-match por
        # sha256 se hace abajo, después de validar el path.
        if book is not None:
            _book_profile = _capmd_config.find_profile_by_name(_cfg.books, book)
            if _book_profile is None:
                raise typer.BadParameter(
                    f"--book {book!r} no está definido en [books.{book}] del TOML"
                )

    if chapter is not None and pages is not None:
        raise typer.BadParameter("--chapter y --pages son mutuamente excluyentes")

    if chapter is not None and pages is not None:
        raise typer.BadParameter("--chapter y --pages son mutuamente excluyentes")

    if output is not None and out_dir is not None:
        raise typer.BadParameter("-o/--output y --out son mutuamente excluyentes")
    if flat and out_dir is None:
        raise typer.BadParameter("--flat requiere --out")

    split_normalized = split.lower() if isinstance(split, str) else None
    if split_normalized is not None:
        if out_dir is None:
            raise typer.BadParameter("--split requiere --out")
        if flat:
            raise typer.BadParameter("--split no aplica con --flat")
        if output is not None:
            raise typer.BadParameter("--split no aplica con -o/--output")
        if split_normalized != "h2":
            raise typer.BadParameter(
                f"--split {split_normalized!r} no soportado; F4 acepta solo 'h2'"
            )

    only_clean_str = only_clean if isinstance(only_clean, str) else None
    skip_clean_str = skip_clean if isinstance(skip_clean, str) else None
    if only_clean_str and skip_clean_str:
        raise typer.BadParameter("--only-clean y --skip-clean son mutuamente excluyentes")

    # F8: --force y --suffix son mutuamente excluyentes.
    if force and suffix:
        raise typer.BadParameter(
            "--force y --suffix son mutuamente excluyentes"
        )

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
    _quiet: bool = bool(ctx.obj.get("quiet", False)) if ctx is not None else False
    _silence_stderr(_quiet)

    # G5 + G3: pre-computar sha256 y resolver perfil de libro por hash antes
    # de pasar al cuerpo de conversión (que ya recibe ``_sha``, ``_cfg``,
    # ``_book_profile``, ``_title_pattern`` con los flags re-bind aplicados).
    _sha: str | None = None
    if source != "-":
        _path_pre = Path(source)
        if _path_pre.exists() and _path_pre.is_file():
            _sha = _maybe_sha256_of(_path_pre)
        if (
            ctx is not None
            and _book_profile is None
            and _cfg is not None
            and _sha
        ):
            _hash_profile = _capmd_config.find_profile_by_hash(_cfg.books, _sha)
            if _hash_profile is not None:
                logger.info(
                    "perfil auto-match por sha256: %s",
                    _hash_profile.name,
                )
                _book_profile = _hash_profile
        if ctx is not None and _book_profile is not None and _cfg is not None:
            _cfg = _capmd_config.apply_book_profile(_cfg, _book_profile)
            _title_pattern = _book_profile.title_pattern
            if not _is_commandline("page_offset") and _cfg.page_offset != 0:
                page_offset = _cfg.page_offset
            if not _is_commandline("image_format") and _cfg.image_format != "png":
                image_format = _cfg.image_format
            if not _is_commandline("out_dir") and _cfg.out_dir is not None:
                out_dir = _cfg.out_dir
            if not _is_commandline("only_clean") and _cfg.cleaners_enabled is not None:
                only_clean = ",".join(_cfg.cleaners_enabled)
            if not _is_commandline("skip_clean") and _cfg.cleaners_disabled is not None:
                skip_clean = ",".join(_cfg.cleaners_disabled)

    _run_convert_body(
        ctx=ctx,
        source=source,
        ext=ext,
        output=output,
        out_dir=out_dir,
        flat=flat,
        page_offset=page_offset,
        pages=pages,
        chapter=chapter,
        no_images=no_images,
        no_anchor=no_anchor,
        no_clean=no_clean,
        only_clean=only_clean,
        skip_clean=skip_clean,
        only_clean_str=only_clean_str,
        skip_clean_str=skip_clean_str,
        split=split,
        split_normalized=split_normalized,
        toc=toc,
        toc_depth=toc_depth,
        report_format=report_format,
        no_warnings=no_warnings,
        strict=strict,
        dry_run=dry_run,
        dry_run_format=dry_run_format,
        force=force,
        suffix=suffix,
        engine=engine,
        llm_client=llm_client,
        llm_model=llm_model,
        keep_raw=keep_raw,
        keep_page_markers=page_markers,
        filter_min_size=filter_min_size,
        filter_repeat_threshold=filter_repeat_threshold,
        filter_background_coverage=filter_background_coverage,
        image_format=image_format,
        image_max_width=image_max_width,
        max_size=max_size,
        max_pages=max_pages,
        timeout=timeout,
        warn_pages=warn_pages,
        no_registry=no_registry,
        open_after=open_after,
        open_cmd=open_cmd,
        _sha=_sha,
        _book_profile=_book_profile,
        _cfg=_cfg,
        _title_pattern=_title_pattern,
        _quiet=_quiet,
    )


def _run_convert_body(
    *,
    ctx: typer.Context | None,
    source: str,
    ext: str | None,
    output: Path | None,
    out_dir: Path | None,
    flat: bool,
    page_offset: int,
    pages: str | None,
    chapter: str | None,
    no_images: bool,
    no_anchor: bool,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    only_clean_str: str | None,
    skip_clean_str: str | None,
    split: str | None,
    split_normalized: str | None,
    toc: bool,
    toc_depth: int,
    report_format: str,
    no_warnings: bool,
    strict: bool,
    dry_run: bool,
    dry_run_format: str,
    force: bool,
    suffix: bool,
    engine: Engine,
    llm_client: Any,
    llm_model: str | None,
    keep_raw: bool,
    keep_page_markers: bool,
    filter_min_size: str | None,
    filter_repeat_threshold: float | None,
    filter_background_coverage: float | None,
    image_format: str,
    image_max_width: int | None,
    max_size: str | None,
    max_pages: int | None,
    timeout: int | None,
    warn_pages: int | None,
    no_registry: bool,
    open_after: bool,
    open_cmd: str | None,
    _sha: str | None,
    _book_profile: Any,
    _cfg: Any,
    _title_pattern: str | None,
    _quiet: bool,
) -> None:
    """Cuerpo principal de ``convert`` envuelto en ``stages()`` (H1).

    Mantiene la lógica previa intacta; el único cambio funcional es:

    - Las 5 stages (``recorte → conversión → limpieza → imágenes →
      escritura``) se avanzan en los call sites correspondientes.
    - El F6 report (``_finalize_and_return``) solo se imprime a stderr
      cuando ``_quiet`` es False.
    """
    sliced_temp: Path | None = None
    extract_pages: list[int] | None = None
    chapter_index: int = 1
    resolved_chapter: Chapter | None = None
    resolved_page_range: PageRange | None = None
    # ``path`` es siempre ``Path`` (mypy no se queja): en la rama
    # stdin usamos un sentinel ``Path("-")`` que nunca se desreferencia
    # porque todos los usos están gateados por ``source != "-"``.
    path: Path
    is_epub = Path(source).suffix.lower() == ".epub" if source != "-" else False
    # Path al .md final que ``--open`` debe abrir tras la escritura.
    final_md_path: Path | None = None

    # Recorte: solo si hay ruta (no stdin) y se va a recortar (pages/chapter).
    with stages(quiet=_quiet) as prog:
        _t_recorte: int | None = None
        _t_conv: int | None = None
        _t_clean: int | None = None
        _t_imgs: int | None = None
        _t_write: int | None = None

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
            _t_conv = prog.start("conversión", total=None)
            result = engine.convert_stream(sys.stdin.buffer, extension=ext)
            prog.stop(_t_conv)
            path = Path("-")  # sentinel; solo existe cuando ``source != "-"``
        else:
            path = Path(source)
            if not path.exists() or not path.is_file():
                raise SourceNotFound(
                    f"no se encontró el archivo: {path}",
                    hint="verificá la ruta o pasá el archivo por stdin con --ext",
                )
            target_path = path
            registry_enabled = not no_registry
            will_slice = chapter is not None or pages is not None
            if will_slice:
                _t_recorte = prog.start("recorte", total=None)

            if chapter is not None:
                if path.suffix.lower() == ".epub":
                    target_path, sliced_temp, resolved_chapter = _resolve_chapter_epub(
                        path, chapter
                    )
                    logger.info("convirtiendo %s (capítulo %r)", path, chapter)
                else:
                    (
                        target_path,
                        sliced_temp,
                        chapter_pages,
                        resolved_page_range,
                        resolved_chapter,
                    ) = _resolve_chapter(
                        path,
                        chapter,
                        page_offset,
                        title_pattern=_title_pattern,
                        sha256_hex=_sha,
                        registry_enabled=registry_enabled,
                    )
                    extract_pages = chapter_pages
                    chapter_index = _chapter_index_from_spec(
                        path,
                        chapter,
                        title_pattern=_title_pattern,
                        sha256_hex=_sha,
                        registry_enabled=registry_enabled,
                    )
                    logger.info(
                        "convirtiendo %s (capítulo %r=%d, offset=%d)",
                        path,
                        chapter,
                        chapter_index,
                        page_offset,
                    )
            elif pages is not None:
                (
                    target_path,
                    sliced_temp,
                    resolved_pages,
                    resolved_page_range,
                ) = _resolve_pages(path, pages, page_offset)
                extract_pages = resolved_pages
                logger.info(
                    "convirtiendo %s (recortado con --pages, offset=%d)",
                    path,
                    pages,
                    page_offset,
                )
            else:
                logger.info("convirtiendo %s", path)

            if _t_recorte is not None:
                prog.stop(_t_recorte)

            _t_conv = prog.start("conversión", total=None)
            result = engine.convert_path(target_path)
            prog.stop(_t_conv)

        result_reported = result
        if sliced_temp is not None:
            sliced_temp.unlink(missing_ok=True)

        if (
            source != "-"
            and not no_registry
            and not dry_run
            and not is_epub
            and _sha
        ):
            _registry_pages = _maybe_page_count(path)
            if _registry_pages:
                try:
                    from capmd.errors import ChapterDetectionFailed

                    try:
                        _chapters_for_registry, _toc_from_outline = _read_outline_cached(
                            path, _sha, registry_enabled=True
                        )
                    except ChapterDetectionFailed:
                        _chapters_for_registry, _toc_from_outline = [], False
                    _register_book(
                        path=path,
                        sha256_hex=_sha,
                        chapters=_chapters_for_registry,
                        pages_total=_registry_pages,
                        toc_from_outline=_toc_from_outline,
                    )
                except Exception as exc:
                    logger.warning("registry: skip por error inesperado (%s)", exc)

        # Imágenes: extracción + anclaje (o marker si --no-images).
        _t_imgs = prog.start("imágenes", total=None)
        if source != "-" and not flat:
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
        cleaners_applied = _collect_cleaners_applied(no_clean, only_clean, skip_clean)
        _t_clean = prog.start("limpieza", total=max(len(cleaners_applied), 1))

        cleaner_stats: list[CleanerStat] = []
        if source == "-":
            final_markdown, cleaner_stats = _apply_clean_pipeline_to_stdin(
                raw_markdown,
                no_clean=no_clean,
                only_clean=only_clean,
                skip_clean=skip_clean,
                ext=ext or "other",
            )
        else:
            final_markdown, cleaner_stats = _apply_clean_pipeline(
                raw_markdown,
                no_clean=no_clean,
                only_clean=only_clean,
                skip_clean=skip_clean,
                target_path=target_path,
            )
        prog.advance(_t_clean)
        prog.stop(_t_clean)

        extracted_figures: list[Figure] = []
        if not flat and (
            no_images
            and source != "-"
            and path.suffix.lower() == ".pdf"
        ):
            final_markdown, anchor_stats = _apply_no_images_marker(
                source_path=path,
                engine=engine,
                extract_pages=extract_pages,
                chapter_index=chapter_index,
                no_clean=no_clean,
                only_clean=only_clean,
                skip_clean=skip_clean,
                keep_page_markers=keep_page_markers,
            )
            cleaner_stats = list(cleaner_stats) + anchor_stats
        elif (
            not flat
            and not no_anchor
            and extraction_result is not None
            and extraction_result[0]
        ):
            final_markdown, anchor_stats = _apply_anchor(
                source_path=path,
                figures=extraction_result[0],
                engine=engine,
                no_clean=no_clean,
                only_clean=only_clean,
                skip_clean=skip_clean,
                keep_page_markers=keep_page_markers,
            )
            cleaner_stats = list(cleaner_stats) + anchor_stats
            extracted_figures = list(extraction_result[0])

        if _t_imgs is not None:
            prog.stop(_t_imgs)

        elapsed_seconds = result.elapsed_seconds

        if keep_raw:
            snapshot_path = write_raw_snapshot(raw_markdown, output_path=output)
            logger.info("snapshot crudo: %s", snapshot_path)
            _stderr.print(f"[dim]snapshot crudo: {snapshot_path}[/dim]")

        if toc:
            from capmd.output.toc import inject_toc
            toc_md = inject_toc(final_markdown, depth=toc_depth)
        else:
            toc_md = final_markdown

        if out_dir is not None or output is not None:
            file_markdown = _prepend_front_matter_for_file(
                final_markdown=toc_md,
                source_path=path if source != "-" else None,
                stdin=source == "-",
                resolved_chapter=resolved_chapter,
                resolved_page_range=resolved_page_range,
                no_clean=no_clean,
                only_clean=only_clean_str,
                skip_clean=skip_clean_str,
            )
            file_title = _resolve_file_title(
                final_markdown=final_markdown,
                resolved_chapter=resolved_chapter,
                source_path=path if source != "-" else None,
                stdin=source == "-",
            )
        else:
            file_markdown = toc_md
            file_title = ""

        from capmd.report import collect_stats, collect_warnings
        _pages = getattr(result_reported, "page_count", None)
        _path_for_format = path if source != "-" else None
        _fmt = _source_format_from(_path_for_format, ext, source)
        _stats_for_warnings = collect_stats(
            raw_markdown=raw_markdown,
            final_markdown=final_markdown,
            pages=_pages,
            figures_count=len(extracted_figures),
            cleaner_stats=tuple(_stats_to_dicts(cleaner_stats)),
            elapsed_seconds=elapsed_seconds,
            source_format=_fmt,
        )
        run_warnings_list = collect_warnings(
            _stats_for_warnings, no_clean=no_clean, format=_fmt
        )
        run_warnings_msgs: tuple[str, ...] = tuple(
            w["message"] for w in run_warnings_list
        )

        if dry_run:
            import shutil
            import tempfile

            from capmd.dryrun import (
                build_dry_run_plan,
                render_plan_json,
                render_plan_text,
            )
            from capmd.report import ReportOutput as _ReportOutput

            _req_out_dir = out_dir
            _req_output = output

            tmp_root: Path | None = None
            try:
                if _req_out_dir is not None:
                    tmp_root = Path(tempfile.mkdtemp(prefix="capmd-dryrun-"))
                    out_dir = tmp_root / _req_out_dir.name
                elif _req_output is not None:
                    tmp_root = Path(tempfile.mkdtemp(prefix="capmd-dryrun-"))
                    output = tmp_root / _req_output.name

                fmt_normalized = dry_run_format.lower()
                if fmt_normalized not in {"json", "text"}:
                    fmt_normalized = "json"
                _report_obj = _ReportOutput(
                    schema_version=1,
                    stats=_stats_for_warnings,
                    warnings=tuple(run_warnings_list),
                    format=fmt_normalized,
                )

                plan = build_dry_run_plan(
                    requested_out_dir=_req_out_dir,
                    requested_output=_req_output,
                    flat=flat,
                    split=split_normalized,
                    toc=toc,
                    toc_depth=toc_depth,
                    no_images=no_images,
                    no_anchor=no_anchor,
                    no_clean=no_clean,
                    only_clean=only_clean_str,
                    skip_clean=skip_clean_str,
                    image_format=image_format,
                    source=str(path) if source != "-" else "<stdin>",
                    source_path=path if source != "-" else None,
                    stdin=source == "-",
                    source_format=_fmt,
                    pages=_pages,
                    size_bytes=getattr(result_reported, "size_bytes", None),
                    sha256=None,
                    resolved_chapter=resolved_chapter,
                    resolved_page_range=resolved_page_range,
                    page_offset=page_offset,
                    final_markdown=final_markdown,
                    report=_report_obj,
                )

                rendered = (
                    render_plan_text(plan)
                    if fmt_normalized == "text"
                    else render_plan_json(plan)
                )
                print(rendered)
                return
            finally:
                if tmp_root is not None and tmp_root.exists():
                    shutil.rmtree(tmp_root, ignore_errors=True)

        # Escritura: el conteo de "writes" depende del layout.
        # 2 = chapter.md + capmd.json (images/ es directorio, no
        # archivo contable en la barra). Con split se agregan sections.
        _write_total = (1 if flat else 2) if out_dir is not None else 1
        _t_write = prog.start("escritura", total=_write_total)

        if out_dir is not None:
            paths = _write_output_tree_or_flat(
                out_dir=out_dir,
                flat=flat,
                source_path=path if source != "-" else None,
                stdin=source == "-",
                resolved_chapter=resolved_chapter,
                resolved_page_range=resolved_page_range,
                final_markdown=file_markdown,
                title=file_title,
                no_clean=no_clean,
                only_clean=only_clean_str,
                skip_clean=skip_clean_str,
                cleaner_stats=tuple(_stats_to_dicts(cleaner_stats)),
                figures=tuple(extracted_figures),
                elapsed_seconds=elapsed_seconds,
                warnings=run_warnings_msgs,
                force=force,
                suffix=suffix,
            )
            if paths is not None and not flat and split_normalized == "h2":
                _write_split_sections(
                    chapter_dir=paths.markdown_path.parent,
                    final_markdown=final_markdown,
                    stdin=source == "-",
                    resolved_chapter=resolved_chapter,
                    resolved_page_range=resolved_page_range,
                    source_path=path if source != "-" else None,
                    no_clean=no_clean,
                    only_clean=only_clean_str,
                    skip_clean=skip_clean_str,
                )
            prog.advance(_t_write)
            prog.stop(_t_write)
            final_md_path = (
                paths.markdown_path
                if paths is not None and paths.markdown_path.exists()
                else None
            )
            _maybe_open_after(open_after, open_cmd, final_md_path, source=source)
            _finalize_and_return(
                raw_markdown=raw_markdown,
                final_markdown=final_markdown,
                pages=getattr(result_reported, "page_count", None),
                figures_count=len(extracted_figures),
                cleaner_stats=cleaner_stats,
                elapsed_seconds=elapsed_seconds,
                source_format=_fmt,
                no_clean=no_clean,
                report_format=report_format,
                strict=strict,
                no_warnings=no_warnings,
                precomputed_stats=_stats_for_warnings,
                precomputed_warnings=run_warnings_list,
                quiet=_quiet,
            )
            return

        if output is None:
            typer.echo(final_markdown)
            prog.advance(_t_write)
            prog.stop(_t_write)
            # Sin path escrito (stdout); ``--open`` no aplica.
            _maybe_open_after(open_after, open_cmd, None, source=source)
            _finalize_and_return(
                raw_markdown=raw_markdown,
                final_markdown=final_markdown,
                pages=getattr(result_reported, "page_count", None),
                figures_count=len(extracted_figures),
                cleaner_stats=cleaner_stats,
                elapsed_seconds=elapsed_seconds,
                source_format=_fmt,
                no_clean=no_clean,
                report_format=report_format,
                strict=strict,
                no_warnings=no_warnings,
                precomputed_stats=_stats_for_warnings,
                precomputed_warnings=run_warnings_list,
                quiet=_quiet,
            )
            return

        from capmd.output.writer import resolve_destination_collision

        output_resolved = resolve_destination_collision(
            output, force=force, suffix=suffix, kind="file"
        )
        if output_resolved != output:
            _stderr.print(f"[dim]destino versionado: {output_resolved}[/dim]")
        output_resolved.write_text(file_markdown, encoding="utf-8")
        logger.debug("escrito %d chars a %s", len(file_markdown), output_resolved)
        prog.advance(_t_write)
        prog.stop(_t_write)
        _maybe_open_after(open_after, open_cmd, output_resolved, source=source)
        _finalize_and_return(
            raw_markdown=raw_markdown,
            final_markdown=final_markdown,
            pages=getattr(result_reported, "page_count", None),
            figures_count=len(extracted_figures),
            cleaner_stats=cleaner_stats,
            elapsed_seconds=elapsed_seconds,
            source_format=_fmt,
            no_clean=no_clean,
            report_format=report_format,
            strict=strict,
            no_warnings=no_warnings,
            precomputed_stats=_stats_for_warnings,
            precomputed_warnings=run_warnings_list,
            quiet=_quiet,
        )


def _prepend_front_matter_for_file(
    *,
    final_markdown: str,
    source_path: Path | None,
    stdin: bool,
    resolved_chapter: Chapter | None,
    resolved_page_range: PageRange | None,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
) -> str:
    """Prepende el front matter YAML para cualquier salida a archivo (F2).

    Stdout no entra por acá (sale por otra rama). Centraliza el cálculo
    de slugs y campos para que ``--out`` (tree/flat) y ``-o FILE``
    compartan exactamente la misma metadata.
    """
    from capmd.errors import IOError as CapmdIOError
    from capmd.output.frontmatter import (
        build_front_matter_fields,
        extract_first_h1,
        markitdown_version,
        prepend_front_matter,
    )
    from capmd.output.writer import (
        _capmd_version,
        _now_iso,
        book_slug_from,
        chapter_slug_from,
    )

    source_doc: SourceDoc | None = None
    if not stdin:
        assert source_path is not None
        fmt = _format_from_suffix(source_path.suffix)
        if fmt == "other":
            raise CapmdIOError(
                f"formato no soportado para front matter: {source_path.suffix}",
                hint="F2 acepta PDF/EPUB/DOCX/PPTX/XLSX como entrada de archivo",
            )
        sha256 = _maybe_sha256_of(source_path) or "0" * 64
        size = source_path.stat().st_size if source_path.exists() else 0
        source_doc = SourceDoc(
            path=source_path,
            format=cast("Literal['pdf', 'epub', 'docx', 'pptx', 'xlsx', 'other']", fmt),
            sha256=sha256,
            size_bytes=size,
        )

    book = book_slug_from(source_doc, stdin=stdin)
    chap = chapter_slug_from(chapter=resolved_chapter, page_range=resolved_page_range)

    title = extract_first_h1(final_markdown)
    if title is None:
        title = resolved_chapter.title if resolved_chapter is not None else book

    pages: list[int] | None
    if resolved_page_range is not None:
        pages = list(resolved_page_range.pages)
    elif resolved_chapter is not None:
        pages = list(range(resolved_chapter.start_page, resolved_chapter.end_page))
    else:
        pages = None

    fields = build_front_matter_fields(
        title=title,
        book_slug=book,
        chapter_slug=chap,
        pages=pages,
        source_file=None if stdin else (source_doc.path.name if source_doc else None),
        source_sha256=None if stdin else (source_doc.sha256 if source_doc else None),
        converted_at=_now_iso(),
        capmd_version=_capmd_version(),
        cleaners_applied=_collect_cleaners_applied(no_clean, only_clean, skip_clean),
        markitdown_version=markitdown_version(),
    )
    return prepend_front_matter(final_markdown, fields)


def _write_output_tree_or_flat(
    *,
    out_dir: Path,
    flat: bool,
    source_path: Path | None,
    stdin: bool,
    resolved_chapter: Chapter | None,
    resolved_page_range: PageRange | None,
    final_markdown: str,
    title: str,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    cleaner_stats: tuple[dict[str, Any], ...] = (),
    figures: tuple[Figure, ...] = (),
    elapsed_seconds: float = 0.0,
    warnings: tuple[str, ...] = (),
    force: bool = False,
    suffix: bool = False,
) -> OutputPaths | None:
    """Rama de escritura para ``--out`` (F1 + F3 + F8).

    Resuelve slugs, arma paths y delega al writer. La resolución de
    colisión (F8) corre sobre el ``chapter_dir``
    (``<out>/<book>/<chapter>/``) y el ``<book>.md`` flat: con
    ``--suffix`` versiona; con ``--force`` fuerza overwrite; sin
    flags falla con ``IOError`` (exit 7).

    En stdin, ``source_path`` es ``None``: el ``book_slug`` cae a
    ``"stdin"`` y ``source_file`` queda ``null`` en el JSON.
    """
    from capmd.errors import IOError as CapmdIOError
    from capmd.output.writer import (
        book_slug_from,
        build_metadata,
        build_tree_paths,
        chapter_slug_from,
        resolve_destination_collision,
        write_output_flat,
        write_output_tree,
    )

    source_doc: SourceDoc | None = None
    if not stdin:
        assert source_path is not None
        fmt = _format_from_suffix(source_path.suffix)
        if fmt == "other":
            raise CapmdIOError(
                f"formato no soportado para árbol de salida: {source_path.suffix}",
                hint="F1 acepta PDF/EPUB/DOCX/PPTX/XLSX como entrada de --out",
            )
        sha256 = _maybe_sha256_of(source_path) or "0" * 64
        size = source_path.stat().st_size if source_path.exists() else 0
        source_doc = SourceDoc(
            path=source_path,
            format=cast("Literal['pdf', 'epub', 'docx', 'pptx', 'xlsx', 'other']", fmt),
            sha256=sha256,
            size_bytes=size,
        )

    book = book_slug_from(source_doc, stdin=stdin)
    chap = chapter_slug_from(chapter=resolved_chapter, page_range=resolved_page_range)
    paths = build_tree_paths(out_dir, book_slug=book, chapter_slug=chap, flat=flat)

    if flat:
        # F8: resolver colisión sobre el archivo flat final.
        new_md_path = resolve_destination_collision(
            paths.markdown_path, force=force, suffix=suffix, kind="file"
        )
        if new_md_path != paths.markdown_path:
            _stderr.print(f"[dim]destino versionado: {new_md_path}[/dim]")
            # Re-derive OutputPaths para el nuevo path; solo cambia ``markdown_path``.
            paths = OutputPaths(
                markdown_path=new_md_path,
                images_dir=None,
                capmd_json_path=None,
                layout="flat",
            )
        md_path = write_output_flat(
            paths, markdown=final_markdown, force=force
        )
        logger.info("flat output: %s", md_path)
        _stderr.print(f"[dim]escrito: {md_path}[/dim]")
        return None

    # Tree: resolver colisión sobre el chapter_dir.
    chapter_dir = paths.markdown_path.parent
    resolved_chapter_dir = resolve_destination_collision(
        chapter_dir, force=force, suffix=suffix, kind="dir"
    )
    if resolved_chapter_dir != chapter_dir:
        _stderr.print(
            f"[dim]destino versionado: {resolved_chapter_dir}[/dim]"
        )
        # Re-armar ``OutputPaths`` apuntando al chapter_dir versionado.
        paths = OutputPaths(
            markdown_path=resolved_chapter_dir / f"{resolved_chapter_dir.name}.md",
            images_dir=resolved_chapter_dir / "images",
            capmd_json_path=resolved_chapter_dir / "capmd.json",
            layout="tree",
        )

    images_relative = "images" if paths.images_dir is not None else None
    metadata = build_metadata(
        source=source_doc,
        stdin=stdin,
        book_slug=book,
        chapter_slug=chap,
        chapter=resolved_chapter,
        page_range=resolved_page_range,
        images_dir_relative=images_relative,
        layout="tree",
        title=title,
        cleaners_applied=_collect_cleaners_applied(no_clean, only_clean, skip_clean),
        cleaner_stats=cleaner_stats,
        figures=figures,
        elapsed_seconds=elapsed_seconds,
        warnings=warnings,
    )
    written = write_output_tree(
        paths, markdown=final_markdown, metadata=metadata, force=force
    )
    logger.info("tree output: %s", written.markdown_path)
    _stderr.print(
        f"[dim]escrito:\n"
        f"  {written.markdown_path}\n"
        f"  {written.capmd_json_path}\n"
        f"  {written.images_dir}/[/dim]"
    )
    return written


def _resolve_file_title(
    *,
    final_markdown: str,
    resolved_chapter: Chapter | None,
    source_path: Path | None,
    stdin: bool,
) -> str:
    """Decide el ``title`` que va al JSON y al FM (F3 + F2).

    Fallback: H1 → ``Chapter.title`` → ``book_slug`` (o ``"stdin"``).
    """
    from capmd.output.frontmatter import extract_first_h1
    from capmd.output.writer import book_slug_from

    h1 = extract_first_h1(final_markdown)
    if h1 is not None:
        return h1
    if resolved_chapter is not None:
        return resolved_chapter.title
    if stdin or source_path is None:
        return "stdin"
    return book_slug_from(_stub_source_doc(source_path), stdin=False)


def _stub_source_doc(source_path: Path) -> SourceDoc:
    """Arma un ``SourceDoc`` mínimo para resolver ``book_slug_from`` sin tocar el FS."""
    fmt = _format_from_suffix(source_path.suffix)
    fmt_literal = cast(
        "Literal['pdf', 'epub', 'docx', 'pptx', 'xlsx', 'other']", fmt
    )
    return SourceDoc(
        path=source_path,
        format=fmt_literal,
        sha256="0" * 64,
        size_bytes=0,
    )


def _stats_to_dicts(stats: list[CleanerStat]) -> list[dict[str, Any]]:
    """Serializa :class:`CleanerStat` a dicts para ``capmd.json`` (F3)."""
    return [
        {
            "name": stat.name,
            "enabled": stat.enabled,
            "changes": stat.changes,
            "duration_ms": round(stat.duration_ms, 3),
            "error": stat.error,
        }
        for stat in stats
    ]


def _write_split_sections(
    *,
    chapter_dir: Path,
    final_markdown: str,
    stdin: bool,
    resolved_chapter: Chapter | None,
    resolved_page_range: PageRange | None,
    source_path: Path | None,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
) -> None:
    """F4: parte el chapter final en secciones H2 y las escribe.

    Crea ``<chapter_dir>/sections/{00-intro.md, 0N-<slug>.md, ..., index.md}``.
    Cada sección lleva un front matter con ``title`` = título del H2; los
    otros 9 campos del FM (F2) son los del chapter padre. Si no se
    detecta ningún H2, emite un warning y NO crea ``sections/``.
    """
    from capmd.errors import IOError as CapmdIOError
    from capmd.output.frontmatter import (
        build_front_matter_fields,
        extract_first_h1,
        markitdown_version,
        prepend_front_matter,
    )
    from capmd.output.split import (
        build_index_markdown,
        extract_h2_sections,
        split_section_filenames,
    )
    from capmd.output.writer import (
        _capmd_version,
        _now_iso,
        book_slug_from,
        chapter_slug_from,
    )

    slice_ = extract_h2_sections(final_markdown)
    sections = slice_.sections
    prelude = slice_.prelude
    has_prelude = bool(prelude.strip())

    if not sections and not has_prelude:
        logger.warning(
            "F4 --split h2: no se detectaron H2 en el output; "
            "no se crea sections/."
        )
        _stderr.print(
            "[yellow]warning:[/yellow] F4 --split h2: sin H2; no se creó sections/"
        )
        return

    sections_dir = chapter_dir / "sections"
    try:
        sections_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise CapmdIOError(
            f"no se pudo crear {sections_dir}",
            hint=str(exc),
        ) from exc

    # Calcular filenames con la misma padding policy.
    filenames, intro_filename = split_section_filenames(
        sections, has_prelude=has_prelude
    )

    # Construir la base del FM (igual para todas las secciones e index).
    if stdin or source_path is None:
        source_doc: SourceDoc | None = None
    else:
        fmt = _format_from_suffix(source_path.suffix)
        sha256 = _maybe_sha256_of(source_path) or "0" * 64
        size = source_path.stat().st_size if source_path.exists() else 0
        source_doc = SourceDoc(
            path=source_path,
            format=cast(
                "Literal['pdf', 'epub', 'docx', 'pptx', 'xlsx', 'other']", fmt
            ),
            sha256=sha256,
            size_bytes=size,
        )

    book = book_slug_from(source_doc, stdin=stdin)
    chap = chapter_slug_from(
        chapter=resolved_chapter, page_range=resolved_page_range
    )

    pages: list[int] | None
    if resolved_page_range is not None:
        pages = list(resolved_page_range.pages)
    elif resolved_chapter is not None:
        pages = list(range(resolved_chapter.start_page, resolved_chapter.end_page))
    else:
        pages = None

    source_file = None if stdin else (source_doc.path.name if source_doc else None)
    source_sha = None if stdin else (source_doc.sha256 if source_doc else None)
    cleaners = _collect_cleaners_applied(no_clean, only_clean, skip_clean)

    chapter_h1 = extract_first_h1(final_markdown) or ""

    def _fields_for(section_title: str) -> dict[str, Any]:
        return build_front_matter_fields(
            title=section_title,
            book_slug=book,
            chapter_slug=chap,
            pages=pages,
            source_file=source_file,
            source_sha256=source_sha,
            converted_at=_now_iso(),
            capmd_version=_capmd_version(),
            cleaners_applied=cleaners,
            markitdown_version=markitdown_version(),
        )

    # Intro (00-intro.md): preludio como body, title = "Prelude".
    if has_prelude and intro_filename is not None:
        intro_path = sections_dir / intro_filename
        intro_md = prepend_front_matter(prelude, _fields_for("Prelude"))
        _write_split_file(intro_path, intro_md)

    # Cada sección.
    for section, filename in zip(sections, filenames, strict=True):
        section_path = sections_dir / filename
        section_md = prepend_front_matter(section.body, _fields_for(section.title))
        _write_split_file(section_path, section_md)

    # Index.
    index_body = build_index_markdown(
        chapter_h1,
        sections,
        filenames,
        intro_filename=intro_filename,
    )
    index_fields = _fields_for(chapter_h1 or "Index")
    index_md = prepend_front_matter(index_body, index_fields)
    _write_split_file(sections_dir / "index.md", index_md)

    logger.info("split output: %d secciones en %s", len(sections), sections_dir)
    _stderr.print(
        f"[dim]secciones ({len(sections)}): {sections_dir}[/dim]"
    )


def _write_split_file(path: Path, content: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        from capmd.errors import IOError as CapmdIOError

        raise CapmdIOError(
            f"no se pudo escribir {path}",
            hint=str(exc),
        ) from exc


def _maybe_sha256_of(path: Path) -> str | None:
    """SHA-256 del archivo si se puede leer, si no ``None``."""
    import hashlib

    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        logger.debug("sha256 falló para %s: %s", path, exc)
        return None


def _maybe_page_count(path: Path) -> int | None:
    """Cantidad de páginas del PDF (1-based) si se puede leer, si no ``None``.

    Usado por G5 para registrar el ``pages_total`` ORIGINAL del libro,
    incluso cuando el convert recortó con ``--chapter`` o ``--pages``
    (en esos casos el sliced PDF tiene menos páginas que el original).
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        return len(PdfReader(str(path)).pages)
    except (FileNotFoundError, PdfReadError, OSError, Exception):
        return None


def _format_from_suffix(suffix: str) -> str:
    """Mapea ``.pdf``/``.epub``/... → :class:`Format`. ``other`` para el resto."""
    s = suffix.lower().lstrip(".")
    if s in {"pdf", "epub", "docx", "pptx", "xlsx"}:
        return s
    return "other"


def _book_title_from_pdf(path: Path) -> str:
    """Devuelve el título humano del PDF: metadata ``/Title`` o filename stem.

    Estrategia (G5):
      1. Intentar ``reader.metadata.title`` (PDF info dict). Si hay
         string no-vacío → normalizado (strip).
      2. Fallback: ``book_slug_from(SourceDoc(path, "pdf", "0"*64, size))``
         sin prefijo ``<stem>`` (slugifier ya devuelve kebab-case).

    Errores de lectura (PDF corrupto) caen al fallback silenciosamente;
    no es crítico para el registry (es solo informativo).
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        reader = PdfReader(str(path))
        meta = reader.metadata
        if meta is not None:
            title = meta.title
            if isinstance(title, str):
                t = title.strip()
                if t:
                    return t
    except (FileNotFoundError, PdfReadError, OSError, Exception):
        pass

    from capmd.models import SourceDoc
    from capmd.output.writer import book_slug_from

    try:
        size = path.stat().st_size if path.exists() else 0
    except OSError:
        size = 0
    source_doc = SourceDoc(path=path, format="pdf", sha256="0" * 64, size_bytes=size)
    return book_slug_from(source_doc)


def _read_outline_cached(
    path: Path,
    sha256_hex: str | None,
    *,
    registry_enabled: bool,
) -> tuple[list[Chapter], bool]:
    """Lee el outline del PDF; usa el registry si hay cache hit (G5).

    Garantía (criterio literal del roadmap G5): si el registry tiene
    una entrada válida para ``sha256_hex`` y ``registry_enabled`` es
    ``True``, NO se invoca :func:`read_outline_with_fallback` sobre
    el archivo.

    Returns:
        ``(chapters, toc_from_outline)`` donde ``toc_from_outline`` es
        ``False`` cuando los capítulos vinieron de la heurística (C8).
        Para el caso cacheado, devuelve el flag original guardado.
    """
    if registry_enabled and sha256_hex:
        cached = lookup_toc(sha256_hex, path=_registry_mod.REGISTRY_PATH)
        if cached is not None and cached.toc:
            logger.debug(
                "registry: cache hit para %s (%d capítulos)",
                path,
                len(cached.toc),
            )
            return list(cached.toc), cached.toc_from_outline

    from capmd.sources.pdf import read_outline_with_fallback

    # ``ChapterDetectionFailed`` se propaga: el caller decide (la CLI
    # lo mapea a exit 4 via _handle_capmd_errors; el bloque de
    # registro lo captura por separado).
    chapters = read_outline_with_fallback(path)
    toc_from_outline = bool(chapters)
    return chapters, toc_from_outline


def _register_book(
    *,
    path: Path,
    sha256_hex: str | None,
    chapters: list[Chapter] | tuple[Chapter, ...],
    pages_total: int,
    toc_from_outline: bool,
) -> None:
    """Persiste el ``BookRecord`` de la corrida en el registry (G5).

    No-op si:
      - ``sha256_hex`` es ``None`` (no se pudo hashear).
      - ``pages_total`` es ``None`` o ``<= 0``.

    Registra incluso cuando ``chapters`` está vacío (PDF sin outline):
    el cache sigue siendo útil para ``pages_total`` y para el
    ``title``/``source_path`` de tracking. ``lookup_toc`` con TOC
    vacío retorna ``None`` y se comporta como miss, así que no
    afecta correctness.

    Los errores se loggean como warning; nunca rompen la corrida.
    """
    if not sha256_hex or not pages_total:
        return
    try:
        title = _book_title_from_pdf(path)
        record = BookRecord(
            sha256=sha256_hex,
            title=title,
            format="pdf",
            pages_total=pages_total,
            toc=tuple(chapters),
            toc_from_outline=toc_from_outline,
            source_path=str(path),
            registered_at=_registry_now_iso(),
            last_seen_at=_registry_now_iso(),
            run_count=1,
        )
        upsert_book(record, path=_registry_mod.REGISTRY_PATH)
        logger.debug(
            "registry: registrado %s con %d capítulos (run #1 inicial)",
            path,
            len(chapters),
        )
    except Exception as exc:
        logger.warning("registry: no se pudo guardar %s (%s); corrida OK", path, exc)


def _registry_now_iso() -> str:
    """ISO 8601 UTC para timestamps del registry."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_DEFAULT_CLEANERS: tuple[str, ...] = (
    "whitespace",
    "quotes",
    "ligatures",
    "hyphens",
    "headers",
    "page_numbers",
    "headings",
    "single_h1",
    "code_blocks",
    "lists",
    "tables",
    "footnotes",
    "paragraph_joins",
)


def _collect_cleaners_applied(
    no_clean: bool, only_clean: str | None, skip_clean: str | None
) -> tuple[str, ...]:
    """Lista efectiva de cleaners de la corrida para ``capmd.json``.

    ``--no-clean`` → tupla vacía. ``--only-clean`` → solo los pedidos.
    ``--skip-clean`` → todos los :data:`_DEFAULT_CLEANERS` menos los
    excluidos. Sin flags → :data:`_DEFAULT_CLEANERS`.
    """
    if no_clean:
        return ()
    if only_clean:
        return tuple(c.strip() for c in only_clean.split(",") if c.strip())
    if skip_clean:
        excluded = {s.strip() for s in skip_clean.split(",") if s.strip()}
        return tuple(c for c in _DEFAULT_CLEANERS if c not in excluded)
    return _DEFAULT_CLEANERS


def _resolve_pages(path: Path, spec: str, offset: int = 0) -> tuple[Path, Path, list[int], PageRange]:
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
    return temp, temp, list(page_range.pages), page_range


def _resolve_chapter(
    path: Path,
    spec: str,
    offset: int = 0,
    *,
    title_pattern: str | None = None,
    sha256_hex: str | None = None,
    registry_enabled: bool = True,
) -> tuple[Path, Path, list[int], PageRange, Chapter]:
    """Hace lookup del capítulo en el outline y devuelve (target, temp, pages).

    ``offset`` desplaza el rango resuelto del capítulo antes de slicear.
    Si la traslación lleva alguna página fuera del documento, se lanza
    ``RangeOutOfBounds`` (exit 4).

    ``title_pattern`` (G3): si está presente y ``spec`` no es numérico,
    se usa como regex case-insensitive contra los títulos del outline;
    si matchea, devuelve ese capítulo. Si no matchea, fallback a
    ``resolve_chapter`` (substring).

    ``sha256_hex`` y ``registry_enabled`` (G5): controlan el cache lookup
    del registry. Si ``registry_enabled=True`` y hay cache hit,
    :func:`read_outline_with_fallback` NO se invoca.

    El tercer elemento es la lista de páginas físicas (1-indexed)
    resueltas para el capítulo, que la fase E1 usa para extraer
    imágenes del PDF original.
    """
    import re

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    from capmd.errors import RangeOutOfBounds, SourceNotFound
    from capmd.sources.chapters import resolve_chapter
    from capmd.sources.pdf import infer_ranges, slice_pdf

    try:
        total = len(PdfReader(str(path)).pages)
    except (FileNotFoundError, PdfReadError) as exc:
        raise SourceNotFound(
            f"no se pudo leer el PDF {path}: {exc}",
            hint="el archivo puede estar corrupto o encriptado",
        ) from exc

    chapters, _toc_from_outline = _read_outline_cached(
        path, sha256_hex, registry_enabled=registry_enabled
    )
    chapters = infer_ranges(chapters, total_pages=total)

    ch: Chapter
    if title_pattern:
        try:
            rgx = re.compile(title_pattern, re.IGNORECASE)
        except re.error:
            rgx = None
        ch = None  # type: ignore[assignment]
        if rgx is not None:
            for candidate in chapters:
                if rgx.search(candidate.title):
                    ch = candidate
                    break
        if ch is None:
            try:
                ch = resolve_chapter(chapters, spec)
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from None
    else:
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
    return temp, temp, pages_list, page_range, ch


def _chapter_index_from_spec(
    path: Path,
    spec: str,
    *,
    title_pattern: str | None = None,
    sha256_hex: str | None = None,
    registry_enabled: bool = True,
) -> int:
    """Resuelve el índice numérico 1-based de un spec de ``--chapter`` (E3).

    Si ``spec`` es numérico, devuelve ese entero directamente. Si no,
    resuelve contra el outline:
      - Si ``title_pattern`` (regex case-insensitive) matchea algún título,
        devuelve el índice del primer match.
      - Si no, fallback a substring case-insensitive del título (default).

    ``sha256_hex`` y ``registry_enabled`` (G5): cache lookup opcional.

    Si el outline no existe o hay ambigüedad, devuelve ``1`` y loggea
    un warning; el nombre de las figuras cae al default sin romper la
    conversión.
    """
    spec = spec.strip()
    try:
        n = int(spec)
    except ValueError:
        n = 0
    if n >= 1:
        return n

    try:
        import re

        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        from capmd.errors import SourceNotFound
        from capmd.sources.chapters import resolve_chapter
        from capmd.sources.pdf import infer_ranges

        try:
            total = len(PdfReader(str(path)).pages)
        except (FileNotFoundError, PdfReadError) as exc:
            raise SourceNotFound(
                f"no se pudo leer el PDF {path}: {exc}",
                hint="el archivo puede estar corrupto o encriptado",
            ) from exc

        chapters, _toc_from_outline = _read_outline_cached(
            path, sha256_hex, registry_enabled=registry_enabled
        )
        chapters = infer_ranges(chapters, total_pages=total)
        if title_pattern:
            try:
                rgx = re.compile(title_pattern, re.IGNORECASE)
            except re.error:
                rgx = None
            if rgx is not None:
                for ch in chapters:
                    if rgx.search(ch.title):
                        return ch.index
        ch = resolve_chapter(chapters, spec)
        return ch.index
    except Exception as exc:
        logger.warning(
            "no se pudo resolver chapter_index para %r; usando 1 (%s)",
            spec,
            exc,
        )
        return 1


def _resolve_chapter_epub(path: Path, spec: str) -> tuple[Path, Path, Chapter]:
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
    return temp, temp, ch


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
) -> tuple[str, list[CleanerStat]]:
    """Aplica el pipeline de cleaners y devuelve ``(markdown, stats)``.

    Helper interno (D1 + D15 + F3) parametrizado por la ruta usada para
    el :class:`SourceDoc`. Lo usan :func:`_apply_clean_pipeline` (flujo
    normal) y :func:`_apply_anchor` (flujo E4 con page markers).

    Con ``--no-clean`` retorna el input intacto y ``stats=[]``.
    """
    if no_clean:
        return raw_markdown, []

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
    cleaned, stats = pipeline.run(raw_markdown, ctx)
    return cleaned, stats


def _apply_anchor(
    *,
    source_path: Path,
    figures: list[Figure],
    engine: Engine,
    no_clean: bool,
    only_clean: str | None,
    skip_clean: str | None,
    keep_page_markers: bool,
) -> tuple[str, list[CleanerStat]]:
    """Re-convierte por página, ancla figuras y devuelve ``(markdown, stats)`` (E4+E5+F3).

    Pipeline:
      1. ``engine.convert_pages(source_path)`` → lista de markdowns por página.
      2. Limpia cada página por separado. Cada invocación a
         :func:`_run_cleaning_pipeline` devuelve stats; las concatenamos
         con sufijo `` (page N)`` para que ``capmd.json`` las muestre
         individualmente.
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
        return "", []

    # Limpiar por página para preservar los markers; agregamos stats con
    # sufijo `` (page N)`` para distinguir corridas repetidas del mismo
    # cleaner.
    cleaned_pages: list[str] = []
    combined_stats: list[CleanerStat] = []
    for page_num, page_text in enumerate(pages, start=1):
        cleaned, stats = _run_cleaning_pipeline(
            page_text,
            source_path=source_path,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
        )
        cleaned_pages.append(cleaned)
        for stat in stats:
            combined_stats.append(
                CleanerStat(
                    name=f"{stat.name} (page {page_num})",
                    enabled=stat.enabled,
                    changes=stat.changes,
                    duration_ms=stat.duration_ms,
                    error=stat.error,
                )
            )

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
    final = anchored if keep_page_markers else strip_page_markers(anchored)
    return final, combined_stats


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
) -> tuple[str, list[CleanerStat]]:
    """Salta extracción y anclaje (E7 ``--no-images``) e inserta placeholders.

    Devuelve ``(markdown, stats)``. Mismo pipeline que :func:`_apply_anchor`
    respecto al manejo de stats por página.
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
        return "", []

    cleaned_pages: list[str] = []
    combined_stats: list[CleanerStat] = []
    for page_num, page_text in enumerate(pages, start=1):
        cleaned, stats = _run_cleaning_pipeline(
            page_text,
            source_path=source_path,
            no_clean=no_clean,
            only_clean=only_clean,
            skip_clean=skip_clean,
        )
        cleaned_pages.append(cleaned)
        for stat in stats:
            combined_stats.append(
                CleanerStat(
                    name=f"{stat.name} (page {page_num})",
                    enabled=stat.enabled,
                    changes=stat.changes,
                    duration_ms=stat.duration_ms,
                    error=stat.error,
                )
            )

    page_areas = _collect_page_areas(source_path, list(range(1, len(cleaned_pages) + 1)))
    placeholders = extract_figure_placeholders(
        source_path,
        pages=list(range(1, len(cleaned_pages) + 1)),
        chapter_index=chapter_index,
        page_areas=page_areas,
    )

    md_with_markers = insert_page_markers(cleaned_pages)
    md_with_placeholders = insert_image_placeholders(md_with_markers, placeholders)
    final = md_with_placeholders if keep_page_markers else strip_page_markers(
        md_with_placeholders
    )
    return final, combined_stats


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


def _source_format_from(path: Path | None, ext: str | None, source: str) -> str:
    """Devuelve la etiqueta de formato del input para el reporte F6."""
    if source == "-":
        return "stdin"
    if path is None:
        return "other"
    return _format_from_suffix(path.suffix) or ext or "other"


def _finalize_and_return(
    *,
    raw_markdown: str,
    final_markdown: str,
    pages: int | None,
    figures_count: int,
    cleaner_stats: list[CleanerStat] | None,
    elapsed_seconds: float,
    source_format: str,
    no_clean: bool,
    report_format: str,
    strict: bool,
    no_warnings: bool,
    precomputed_stats: Any = None,
    precomputed_warnings: list[dict[str, Any]] | None = None,
    quiet: bool = False,
) -> None:
    """F6: construye, persiste y emite el reporte de calidad al final.

    Reusa ``precomputed_stats`` y ``precomputed_warnings`` cuando vienen
    dados (computados antes del tree write para persistir warnings en
    ``capmd.json``). Si no, los recalcula aquí.

    Si ``--strict`` y hay warnings → ``typer.Exit(8)``.

    Con ``--quiet`` (``quiet=True``) el reporte NO se imprime a stderr
    pero ``--strict`` sigue evaluándose (los warnings que harían fallar
    a CI no se silencian: el ``exit 8`` es la señal que importa).
    """
    from capmd.report import (
        ReportOutput,
        collect_stats,
        collect_warnings,
        render_json,
        render_text,
    )

    if precomputed_stats is None:
        stats = collect_stats(
            raw_markdown=raw_markdown,
            final_markdown=final_markdown,
            pages=pages,
            figures_count=figures_count,
            cleaner_stats=tuple(_stats_to_dicts(cleaner_stats or [])),
            elapsed_seconds=elapsed_seconds,
            source_format=source_format,
        )
    else:
        stats = precomputed_stats
    if precomputed_warnings is None:
        warnings_list = (
            []
            if no_warnings
            else collect_warnings(stats, no_clean=no_clean, format=source_format)
        )
    else:
        warnings_list = precomputed_warnings

    fmt_normalized = report_format.lower()
    if fmt_normalized not in {"json", "text"}:
        fmt_normalized = "json"
    report = ReportOutput(
        schema_version=1,
        stats=stats,
        warnings=tuple(warnings_list),
        format=fmt_normalized,
    )

    if not quiet:
        formatted = (
            render_text(report)
            if fmt_normalized == "text"
            else render_json(report)
        )
        _stderr.print(formatted)
    if strict and report.warnings:
        raise typer.Exit(8)


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
) -> tuple[str, list[CleanerStat]]:
    """Aplica el pipeline de cleaners y devuelve ``(markdown, stats)``.

    ``--no-clean`` devuelve el input intacto y ``stats=[]``.
    ``--only-clean`` y ``--skip-clean`` filtran el pipeline por defecto.
    Construye un ``CleanContext`` mínimo a partir de la ruta de salida.
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
) -> tuple[str, list[CleanerStat]]:
    """Variante para stdin: usa un path placeholder en ``SourceDoc``."""
    if no_clean:
        return raw_markdown, []

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
    final_markdown, stats = pipeline.run(raw_markdown, ctx)
    return final_markdown, stats


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
    no_registry: bool = typer.Option(
        False,
        "--no-registry",
        help=(
            "(G5) No leer el registry local de libros: forzar re-lectura "
            "del outline desde el PDF."
        ),
    ),
) -> None:
    """Imprime el índice (TOC) del archivo en forma de árbol o JSON."""
    import json

    from capmd.cli_render import chapters_to_json_dict, render_outline_tree
    from capmd.errors import SourceNotFound
    from capmd.sources.pdf import infer_ranges

    if source.suffix.lower() == ".epub":
        from capmd.sources.epub import read_outline as read_outline_epub

        chapters = read_outline_epub(source)
        total_pages = len(chapters)
    else:
        # G5: cache lookup opcional del registry.
        sha = _maybe_sha256_of(source) if not no_registry else None
        chapters, _toc_from_outline = _read_outline_cached(
            source, sha, registry_enabled=not no_registry
        )
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


# ---------------------------------------------------------------------------
# G4: `capmd config init` / `capmd config show`
# ---------------------------------------------------------------------------


def _resolve_config_target(target: str) -> Path:
    """Mapea ``'project' | 'global'`` → Path concreto.

    Project se resuelve contra ``Path.cwd()`` (no contra el ``capmd.toml``
    del módulo config, que podría estar en otro lado).

    Global se recomputa desde ``$HOME`` en CADA llamada, no desde el
    ``GLOBAL_TOML`` cacheado al import, para que ``monkeypatch.setenv``
    (e.g. en tests) funcione.
    """
    if target == "global":
        from pathlib import Path as _Path

        return _Path.home() / ".config" / "capmd" / "config.toml"
    if target == "project":
        from pathlib import Path as _Path

        return _Path.cwd() / "capmd.toml"
    raise ValueError(f"target inválido: {target!r}")


@config_app.command("init")
@_handle_capmd_errors
def config_init(
    target: str = typer.Option(
        "project",
        "--target",
        case_sensitive=False,
        help=(
            "Dónde escribir: 'project' (./capmd.toml) o 'global' "
            "(~/.config/capmd/config.toml)."
        ),
    ),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Imprime el TOML a stdout en vez de escribir un archivo.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Sobreescribe si el destino existe.",
    ),
) -> None:
    """Genera un ``capmd.toml`` starter comentado con todas las claves."""
    from capmd.config_init import render_default_toml

    target_normalized = target.lower()
    if target_normalized not in {"project", "global"}:
        raise typer.BadParameter(
            f"--target {target!r} no es válido; usar 'project' o 'global'"
        )

    content = render_default_toml(target=target_normalized)

    if stdout:
        typer.echo(content, nl=False)
        return

    path = _resolve_config_target(target_normalized)
    if path.exists() and not force:
        # No usamos CapmdError (es para fuentes, no para I/O de usuario);
        # usamos typer.Exit con código 8 (mismo que F8 destination
        # collision, para consistencia semántica).
        typer.echo(
            f"error: {path} ya existe; usá --force para sobreescribir",
            err=True,
        )
        raise typer.Exit(code=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    typer.echo(f"escrito: {path}", err=True)


@config_app.command("show")
@_handle_capmd_errors
def config_show(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Salida JSON en vez de tabla.",
    ),
    book: str | None = typer.Option(
        None,
        "--book",
        help="Aplica el perfil de libro antes de mostrar el resultado.",
    ),
) -> None:
    """Muestra la config efectiva resuelta y la trace de procedencia."""
    import os as _os

    from capmd import config as _config_mod
    from capmd.config_show import render_json, render_table

    cfg = _config_mod.load_config(env=_os.environ)

    if book is not None:
        profile = _config_mod.find_profile_by_name(cfg.books, book)
        if profile is None:
            raise typer.BadParameter(
                f"--book {book!r} no está definido en [books.{book}] del TOML"
            )
        cfg = _config_mod.apply_book_profile(cfg, profile)

    if json_output:
        typer.echo(render_json(cfg), nl=False)
    else:
        typer.echo(render_table(cfg), nl=False)


@app.command()
@_handle_capmd_errors
def batch(
    ctx: typer.Context,
    source: Path = typer.Argument(  # noqa: B008
        ...,
        help="PDF o EPUB a procesar.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    chapters: str = typer.Option(
        ...,
        "--chapters",
        help=(
            "(H2) Capítulos a convertir por índice 1-based del outline. "
            "Sintaxis: '1-12', '1,3,5', '1-3,7,10-12'. Acepta solo rangos "
            "cerrados y números enteros (no nombres)."
        ),
    ),
    out_dir: Path = typer.Option(  # noqa: B008
        ...,
        "--out",
        help=(
            "(H2) Directorio padre del batch. ``capmd convert`` creará "
            "``<out>/<book-slug>/<chapter-slug>/{file.md, images/, capmd.json}`` "
            "por capítulo. Auto-creado si no existe."
        ),
    ),
    jobs: int = typer.Option(
        0,
        "--jobs",
        min=0,
        max=32,
        help=(
            "(H2) Workers en paralelo. 0 = ``min(cpu_count, len(chapters))``. "
            "1 = secuencial (útil para debug)."
        ),
    ),
    book: str | None = typer.Option(
        None,
        "--book",
        help="(G3) Perfil declarado en ``[books.\"<id>\"]`` del TOML.",
    ),
    page_offset: int = typer.Option(
        0,
        "--page-offset",
        help="(C7) Traducción paginación impresa → física.",
    ),
    flat: bool = typer.Option(
        False,
        "--flat",
        help="(F1) Output sin images/ ni capmd.json por capítulo.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "(F8) Sobrescribir chapter dirs existentes. Sin este flag, "
            "``capmd convert`` falla si el destino ya existe (exit 7)."
        ),
    ),
    suffix: bool = typer.Option(
        False,
        "--suffix",
        help="(F8) Versionar con sufijo numérico en lugar de sobrescribir.",
    ),
    image_format: str = typer.Option(
        "png",
        "--image-format",
        case_sensitive=False,
        help="(E1) Formato de imágenes extraídas: 'png' o 'webp'.",
    ),
    image_max_width: int | None = typer.Option(
        None,
        "--image-max-width",
        min=1,
        help="(E1) Ancho máximo en píxeles para las imágenes extraídas.",
    ),
    filter_min_size: str | None = typer.Option(
        None, "--filter-min-size", help="(E2) Tamaño mínimo WxH (ej: '64x64')."
    ),
    filter_repeat_threshold: float | None = typer.Option(
        None,
        "--filter-repeat-threshold",
        min=0.0,
        max=1.0,
        help="(E2) Fracción de páginas para tratar una imagen como logo.",
    ),
    filter_background_coverage: float | None = typer.Option(
        None,
        "--filter-background-coverage",
        min=0.0,
        max=1.0,
        help="(E2) Cobertura mínima para tratar imagen como fondo.",
    ),
    no_images: bool = typer.Option(
        False,
        "--no-images",
        help="(E7) Saltar extracción e insertar placeholders.",
    ),
    no_anchor: bool = typer.Option(
        False,
        "--no-anchor",
        help="(E4) No insertar ![](images/...) en el markdown.",
    ),
    page_markers: bool = typer.Option(
        False,
        "--page-markers",
        help="(D5/E4) Conservar centinelas <!-- page N --> en el output.",
    ),
    no_clean: bool = typer.Option(
        False, "--no-clean", help="(D) Saltear todos los cleaners."
    ),
    only_clean: str | None = typer.Option(
        None, "--only-clean", help="(D) Lista separada por comas de cleaners a ejecutar."
    ),
    skip_clean: str | None = typer.Option(
        None, "--skip-clean", help="(D) Lista separada por comas de cleaners a saltar."
    ),
    split: str | None = typer.Option(
        None,
        "--split",
        case_sensitive=False,
        help=(
            "(F4) Por capítulo, parte por H2 en una subcarpeta sections/. "
            "Solo 'h2'. Incompatible con --flat."
        ),
    ),
    toc: bool = typer.Option(
        False,
        "--toc",
        help="(F5) Insertar TOC al inicio del .md de cada capítulo.",
    ),
    toc_depth: int = typer.Option(
        3,
        "--toc-depth",
        min=2,
        max=6,
        help="(F5) Nivel máximo de headings en la TOC.",
    ),
    no_registry: bool = typer.Option(
        False,
        "--no-registry",
        help=("(G5) No usar el cache de outline local ni escribir el registry."),
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        is_flag=True,
        help=(
            "(H1) Silencia progreso y logs (gana sobre ``-v``). H2 también "
            "omite el reporte por capítulo y el resumen final."
        ),
    ),
) -> None:
    """Convierte varios capítulos de un libro en paralelo (H2)."""
    if force and suffix:
        raise typer.BadParameter("--force y --suffix son mutuamente excluyentes")
    if flat and split is not None:
        raise typer.BadParameter("--flat y --split son mutuamente excluyentes")
    if only_clean and skip_clean:
        raise typer.BadParameter("--only-clean y --skip-clean son mutuamente excluyentes")
    if split is not None and split.lower() not in {"h2", "h3"}:
        raise typer.BadParameter(f"--split {split!r} no soportado; F4 acepta 'h2'")
    if split is not None and split.lower() == "h3":
        # F4 solo soporta h2; verificamos de forma explícita para mensajes claros.
        raise typer.BadParameter("--split h3 no soportado todavía")

    quiet_effective = quiet or bool(
        ctx.obj.get("quiet", False) if ctx is not None else False
    )

    if not source.exists() or not source.is_file():
        raise SourceNotFound(
            f"no se encontró el archivo: {source}",
            hint="verificá la ruta",
        )
    if source.suffix.lower() not in {".pdf", ".epub"}:
        raise UnsupportedFormat(
            f"capmd batch no soporta {source.suffix!r}; usa PDF o EPUB",
            hint="para otros formatos, convertí con ``capmd convert``",
        )

    from capmd.batch import run_batch as _run_batch

    sha = _maybe_sha256_of(source)
    chapters_list: list[Chapter] = []
    if source.suffix.lower() == ".pdf":
        try:
            chapters_list, _toc_from_outline = _read_outline_cached(
                source,
                sha,
                registry_enabled=bool(
                    ctx.obj.get("registry_enabled", not no_registry)
                    if ctx is not None
                    else not no_registry
                ),
            )
        except Exception:
            # Sin outline (C8 cae a heurística). Si parse_chapters_spec
            # recibe total=0 falla con mensaje claro.
            chapters_list = []

    try:
        indices = _parse_chapters_spec(chapters, total=len(chapters_list))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    if not indices:
        raise typer.BadParameter(
            "--chapters no resolvió ningún capítulo válido"
        )

    # Args comunes para cada capmd convert worker. El sub-proceso hereda
    # el venv actual, así que ``--quiet`` se respeta localmente.
    common_args: list[str] = []
    if book is not None:
        common_args += ["--book", book]
    if page_offset:
        common_args += ["--page-offset", str(page_offset)]
    if flat:
        common_args += ["--flat"]
    if force:
        common_args += ["--force"]
    elif suffix:
        common_args += ["--suffix"]
    if image_format.lower() != "png":
        common_args += ["--image-format", image_format]
    if image_max_width is not None:
        common_args += ["--image-max-width", str(image_max_width)]
    if filter_min_size is not None:
        common_args += ["--filter-min-size", filter_min_size]
    if filter_repeat_threshold is not None:
        common_args += ["--filter-repeat-threshold", str(filter_repeat_threshold)]
    if filter_background_coverage is not None:
        common_args += ["--filter-background-coverage", str(filter_background_coverage)]
    if no_images:
        common_args += ["--no-images"]
    elif no_anchor:
        common_args += ["--no-anchor"]
    if page_markers:
        common_args += ["--page-markers"]
    if no_clean:
        common_args += ["--no-clean"]
    elif only_clean:
        common_args += ["--only-clean", only_clean]
    elif skip_clean:
        common_args += ["--skip-clean", skip_clean]
    if split is not None:
        common_args += ["--split", "h2"]
    if toc:
        common_args += ["--toc", "--toc-depth", str(toc_depth)]
    if no_registry:
        common_args += ["--no-registry"]

    summary = _run_batch(
        pdf_path=source,
        out_dir=out_dir,
        chapter_indices=indices,
        common_args=common_args,
        jobs=jobs,
        quiet=quiet_effective,
    )

    if summary.failed > 0:
        raise typer.Exit(code=1)


@app.command()
@_handle_capmd_errors
def inspect(
    ctx: typer.Context,
    source: Path = typer.Argument(  # noqa: B008
        ...,
        help="PDF o EPUB a diagnosticar.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    format: str = typer.Option(
        "text",
        "--format",
        case_sensitive=False,
        help="(H3) Formato de salida: 'text' (rich table, default) o 'json'.",
    ),
    sample: int = typer.Option(
        20,
        "--sample",
        min=1,
        max=1000,
        help=(
            "(H3) Páginas a muestrear para fuentes y headers/footers. "
            "Default: 20. Subir para más precisión en PDFs grandes."
        ),
    ),
    no_outline: bool = typer.Option(
        False, "--no-outline", help="(H3) Saltar análisis de outline."
    ),
    no_text: bool = typer.Option(
        False, "--no-text", help="(H3) Saltar conteo de palabras por página."
    ),
    no_fonts: bool = typer.Option(
        False, "--no-fonts", help="(H3) Saltar enumeración de fuentes."
    ),
    no_headers_footers: bool = typer.Option(
        False,
        "--no-headers-footers",
        help="(H3) Saltar detección de headers/footers repetidos.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        is_flag=True,
        help="(H1) Silencia el log a stderr; stdout mantiene el reporte.",
    ),
) -> None:
    """Diagnóstico estructural de un PDF sin convertirlo (H3)."""
    fmt_norm = format.lower()
    if fmt_norm not in {"text", "json"}:
        raise typer.BadParameter(
            f"--format {format!r} no soportado; usar 'text' o 'json'"
        )

    quiet_effective = quiet or bool(
        ctx.obj.get("quiet", False) if ctx is not None else False
    )

    from capmd.inspect import inspect_pdf as _inspect_pdf
    from capmd.inspect import render_json, render_text

    report = _inspect_pdf(
        source,
        sample=sample,
        include_outline=not no_outline,
        include_text=not no_text,
        include_fonts=not no_fonts,
        include_headers_footers=not no_headers_footers,
    )

    if fmt_norm == "json":
        typer.echo(render_json(report))
    else:
        typer.echo(render_text(report))

    # Si quiet: nada a stderr (log ya está silenciado por configure_quiet).
    _ = quiet_effective


def _maybe_open_after(
    open_after: bool,
    open_cmd: str | None,
    final_md_path: Path | None,
    *,
    source: str,
) -> None:
    """Helper de H5: si ``--open`` está activo y hay path escrito, abre."""
    if not open_after:
        return
    if source == "-":
        # Sin archivo al disco; ``capmd open`` cubre el caso de re-abrir.
        typer.echo(
            "[yellow]--open: sin archivo en disco (stdin). "
            "Usá ``capmd open <file>`` después de convertir.[/yellow]",
            err=True,
        )
        return
    if final_md_path is None or not final_md_path.exists():
        typer.echo(
            "[yellow]--open: no se pudo determinar el archivo a abrir.[/yellow]",
            err=True,
        )
        return
    from capmd.open import open_in_editor

    try:
        open_in_editor(final_md_path, editor=open_cmd)
    except typer.BadParameter as exc:
        raise typer.BadParameter(f"--open: {exc}") from None
    except FileNotFoundError as exc:
        raise typer.BadParameter(
            f"--open: editor no encontrado ({exc.filename or exc.strerror}). "
            "Verificá $EDITOR o --open-cmd."
        ) from None
