"""Árbol de salida de capmd (F1 + F3).

Construye la estructura versionable::

    <DIR>/<book-slug>/<chapter-slug>/
        ├── <chapter-slug>.md
        ├── images/
        └── capmd.json

a partir de un ``SourceDoc`` (o stdin) y un :class:`Chapter` / :class:`PageRange`
resuelto. ``--flat`` reduce el árbol a ``<DIR>/<book-slug>.md``.

``capmd.json`` sigue el schema versionado: SCHEMA_VERSION=2 (F3). F3 agrega
los campos ``title``, ``markitdown_version``, ``elapsed_seconds``,
``warnings``, ``cleaner_stats`` y ``figures`` para que el JSON permita
regenerar el front matter sin tocar el original.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from capmd.errors import IOError
from capmd.models import Chapter, Figure, PageRange, SourceDoc

__all__ = [
    "CapmdJsonV2",
    "OutputPaths",
    "book_slug_from",
    "build_capmd_json_v2",
    "build_metadata",
    "build_tree_paths",
    "chapter_slug_from",
    "markitdown_version",
    "resolve_destination_collision",
    "slugify",
    "write_output_flat",
    "write_output_tree",
]


SCHEMA_VERSION = 2
_CAPMD_VERSION_CACHE: str | None = None


def _now_iso(now: datetime | None = None) -> str:
    """ISO 8601 UTC con sufijo ``Z``, segundos de resolución. Inyectable."""
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
_NON_SLUG_RUN = re.compile(r"[^\w]+", re.UNICODE)
_MULTI_DASH = re.compile(r"-{2,}")
_ASCII_NON_SLUG_RUN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class OutputPaths:
    """Paths resueltos del árbol de salida."""

    markdown_path: Path
    images_dir: Path | None
    capmd_json_path: Path | None
    layout: str  # "tree" | "flat"


@dataclass(frozen=True)
class CapmdJsonV2:
    """Metadata completa de una corrida (schema_version=2, F3).

    20 campos base + 4 campos opcionales de ``study`` (K2). Las listas
    (``cleaner_stats``, ``figures``, ``warnings``) están **siempre
    presentes**, vacías si no hay datos. Los campos ``study_*`` se
    omiten del JSON cuando todos están en su valor neutro (compat con
    ``capmd.json`` pre-K2 + reduce ruido en corridas sin ``--profile study``).
    """

    book_slug: str
    chapter_slug: str
    title: str
    source_file: str | None
    source_sha256: str | None
    pages: tuple[int, ...] | None
    range_label: str
    chapter: dict[str, Any] | None
    generated_at: str
    capmd_version: str
    markitdown_version: str
    images_dir: str | None
    layout: str
    elapsed_seconds: float
    cleaner_stats: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    figures: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    cleaners_applied: tuple[str, ...] = field(default_factory=tuple)
    study_tags: tuple[str, ...] = field(default_factory=tuple)
    reading_status: str = "unread"
    started_at: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        if self.elapsed_seconds < 0:
            raise ValueError(
                f"elapsed_seconds must be >= 0, got {self.elapsed_seconds}"
            )

    def as_json(self) -> str:
        return json.dumps(
            self._as_dict(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )

    def _as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "book_slug": self.book_slug,
            "chapter": self.chapter,
            "chapter_slug": self.chapter_slug,
            "cleaner_stats": list(self.cleaner_stats),
            "cleaners_applied": list(self.cleaners_applied),
            "capmd_version": self.capmd_version,
            "elapsed_seconds": self.elapsed_seconds,
            "figures": list(self.figures),
            "generated_at": self.generated_at,
            "images_dir": self.images_dir,
            "layout": self.layout,
            "markitdown_version": self.markitdown_version,
            "pages": list(self.pages) if self.pages is not None else None,
            "range_label": self.range_label,
            "schema_version": SCHEMA_VERSION,
            "source_file": self.source_file,
            "source_sha256": self.source_sha256,
            "title": self.title,
            "warnings": list(self.warnings),
        }
        # K2: campos study opcionales. Solo se emiten si alguno diverge
        # del neutro (compat con capmd.json pre-K2).
        if _study_is_active(
            self.study_tags, self.reading_status, self.started_at, self.finished_at
        ):
            d["finished_at"] = self.finished_at
            d["reading_status"] = self.reading_status
            d["started_at"] = self.started_at
            d["study_tags"] = list(self.study_tags)
        return d


def _study_is_active(
    tags: tuple[str, ...], status: str, started: str | None, finished: str | None
) -> bool:
    """``True`` si los 4 campos study no son todos neutrales."""
    return bool(tags) or status != "unread" or started is not None or finished is not None


def _capmd_version() -> str:
    global _CAPMD_VERSION_CACHE
    if _CAPMD_VERSION_CACHE is None:
        try:
            _CAPMD_VERSION_CACHE = metadata.version("capmd")
        except metadata.PackageNotFoundError:  # pragma: no cover
            _CAPMD_VERSION_CACHE = "0.0.0+unknown"  # pragma: no cover
    return _CAPMD_VERSION_CACHE


_MARKITDOWN_VERSION_CACHE: str | None = None


def markitdown_version() -> str:
    """Versión instalada de ``markitdown``. ``"unknown"`` si no está disponible."""
    global _MARKITDOWN_VERSION_CACHE
    if _MARKITDOWN_VERSION_CACHE is None:
        try:
            _MARKITDOWN_VERSION_CACHE = metadata.version("markitdown")
        except metadata.PackageNotFoundError:  # pragma: no cover
            _MARKITDOWN_VERSION_CACHE = "unknown"  # pragma: no cover
    return _MARKITDOWN_VERSION_CACHE


def slugify(text: str, *, max_length: int = 60) -> str:
    """Devuelve un slug kebab-case ASCII a partir de ``text``.

    Reglas:
      - NFC + NFKD: descompone acentos y descarta marks (``á`` → ``a``).
      - lowercase.
      - Cualquier run de caracteres que no sea ``[a-z0-9]`` se colapsa a ``-``.
      - Strip ``-`` al inicio y al final.
      - Si queda vacío, devuelve ``"untitled"``.
      - Trunca a ``max_length`` (sin dejar ``-`` al final).

    Caracteres no-ASCII que sobreviven la normalización (CJK, cirílico,
    etc.) se conservan tal cual: APFS los soporta y un slug unicode sigue
    siendo válido como nombre de carpeta legible.
    """
    if not text:
        return "untitled"

    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    lowered = stripped.lower()
    has_non_ascii = any(ord(ch) > 127 for ch in lowered)
    slug = _NON_SLUG_RUN.sub("-", lowered).strip("-") if has_non_ascii else _ascii_slugify(lowered)
    if not slug:
        return "untitled"
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def _ascii_slugify(lowered: str) -> str:
    """Slug estricto: solo ``[a-z0-9]``. Resto → ``-``. Colapsa guiones duplicados."""
    slug = _ASCII_NON_SLUG_RUN.sub("-", lowered).strip("-")
    return _MULTI_DASH.sub("-", slug)


def book_slug_from(
    source: SourceDoc | None,
    *,
    stdin: bool = False,
) -> str:
    """Devuelve el slug del libro a partir del ``SourceDoc`` o del flag ``stdin``."""
    if stdin or source is None:
        return "stdin"
    return slugify(source.path.stem)


_CHAPTER_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:chapter|cap[íi]tulo|cap\.?|secci[óo]n|section|part|parte)\s+\d+\s*[:.\-]\s*",
    re.IGNORECASE,
)


def _chapter_title_slug(title: str) -> str:
    """Slug del título con dos pases:

    1. Strip prefijo ``Chapter N:``/``Capítulo N:``/etc. si está presente
       (eso ya queda implícito en el ``cap-NN`` del slug completo).
    2. :func:`slugify` sobre lo restante.
    """
    stripped = _CHAPTER_TITLE_PREFIX_RE.sub("", title).strip() or title.strip()
    slug = slugify(stripped)
    return slug


def chapter_slug_from(
    *,
    chapter: Chapter | None,
    page_range: PageRange | None,
) -> str:
    """Devuelve el slug del capítulo según la fuente disponible.

    Prioridad:
      1. ``Chapter`` resuelto por ``--chapter`` → ``cap-NN-<title-slug>``.
         El prefijo ``Chapter N:`` del título se elimina del slug (ya
         queda implícito en el ``cap-NN``); el ``chapter.title`` original
         se conserva en ``capmd.json``.
      2. ``PageRange`` (de ``--pages`` o de un chapter pasado por offset) →
         ``pages-START-END``. Si la lista no es contigua, lista los 1eros
         8 valores unidos por ``-`` para no explotar el nombre.
      3. Sin selección → ``"full"``.
    """
    if chapter is not None:
        title = _chapter_title_slug(chapter.title)
        return f"cap-{chapter.index:02d}-{title}" if title else f"cap-{chapter.index:02d}"

    if page_range is not None:
        pages = page_range.pages
        if len(pages) == 1:
            return f"pages-{pages[0]}-{pages[0]}"
        if _is_contiguous(pages):
            return f"pages-{pages[0]}-{pages[-1]}"
        head = "-".join(str(p) for p in pages[:8])
        suffix = "" if len(pages) <= 8 else "-more"
        return f"pages-{head}{suffix}"

    return "full"


def _is_contiguous(pages: tuple[int, ...]) -> bool:
    return all(pages[i] + 1 == pages[i + 1] for i in range(len(pages) - 1))


def range_label_from(
    *,
    chapter: Chapter | None,
    page_range: PageRange | None,
) -> str:
    """Etiqueta humana corta del rango. ``"full"`` cuando no hay selección.

    Si hay ``page_range`` la usa; si solo hay ``chapter``, deriva las
    páginas de ``start_page``..``end_page - 1``. Si no hay ninguna, ``"full"``.
    """
    pages: tuple[int, ...]
    if page_range is not None:
        pages = page_range.pages
    elif chapter is not None:
        pages = tuple(range(chapter.start_page, chapter.end_page))
    else:
        return "full"

    if len(pages) == 1:
        return str(pages[0])
    if _is_contiguous(pages):
        return f"{pages[0]}-{pages[-1]}"
    head = ",".join(str(p) for p in pages[:8])
    suffix = "" if len(pages) <= 8 else ",…"
    return f"{head}{suffix}"


def build_tree_paths(
    out_dir: Path,
    *,
    book_slug: str,
    chapter_slug: str,
    flat: bool,
) -> OutputPaths:
    """Construye (sin tocar el FS) las rutas del árbol o del flat layout."""
    if flat:
        return OutputPaths(
            markdown_path=out_dir / f"{book_slug}.md",
            images_dir=None,
            capmd_json_path=None,
            layout="flat",
        )
    chapter_dir = out_dir / book_slug / chapter_slug
    return OutputPaths(
        markdown_path=chapter_dir / f"{chapter_slug}.md",
        images_dir=chapter_dir / "images",
        capmd_json_path=chapter_dir / "capmd.json",
        layout="tree",
    )


def write_output_tree(
    paths: OutputPaths,
    *,
    markdown: str,
    metadata: CapmdJsonV2,
    force: bool = False,
) -> OutputPaths:
    """Crea el árbol completo y escribe ``.md`` + ``capmd.json``.

    ``paths.layout`` debe ser ``"tree"`` (ver
    :func:`build_tree_paths`).

    Crea ``images/`` vacía si no existía para que el árbol quede
    versionable desde la primera corrida. Si la carpeta del capítulo ya
    existe: con ``force=True`` la borra (``shutil.rmtree``) y recrea;
    sin ``force``: falla con :class:`IOError` (el caller de F8 ya
    resolvió colisiones vía ``--suffix``; este check es la red de
    seguridad).
    """
    import shutil

    if paths.layout != "tree":
        raise ValueError(  # pragma: no cover
            f"write_output_tree requiere layout='tree', recibió {paths.layout!r}"
        )
    assert paths.capmd_json_path is not None
    assert paths.images_dir is not None

    chapter_dir = paths.markdown_path.parent
    if chapter_dir.exists():
        if force:
            try:
                shutil.rmtree(chapter_dir)
            except OSError as exc:  # pragma: no cover
                raise IOError(  # pragma: no cover
                    f"no se pudo borrar el destino existente {chapter_dir}",
                    hint=str(exc),
                ) from exc
        else:
            raise IOError(
                f"el directorio de salida ya existe: {chapter_dir}",
                hint=(
                    "usá --force para sobrescribir o --suffix para versionar"
                ),
            )

    try:
        chapter_dir.mkdir(parents=True, exist_ok=False)
        paths.images_dir.mkdir(exist_ok=False)
    except OSError as exc:  # pragma: no cover
        raise IOError(  # pragma: no cover
            f"no se pudo crear el árbol de salida en {chapter_dir}",
            hint=str(exc),
        ) from exc

    _write_text(paths.markdown_path, markdown)
    _write_text(paths.capmd_json_path, metadata.as_json() + "\n")
    return paths


def write_output_flat(
    paths: OutputPaths,
    *,
    markdown: str,
    force: bool = False,
) -> Path:
    """Escribe solo el ``.md`` en modo flat.

    Si el archivo ya existe: con ``force=True`` lo borra antes; sin
    ``force``: falla con :class:`IOError`.

    ``paths.layout`` debe ser ``"flat"``.
    """
    if paths.layout != "flat":
        raise ValueError(  # pragma: no cover
            f"write_output_flat requiere layout='flat', recibió {paths.layout!r}"
        )

    parent = paths.markdown_path.parent
    if paths.markdown_path.exists():
        if force:
            try:
                paths.markdown_path.unlink()
            except OSError as exc:  # pragma: no cover
                raise IOError(  # pragma: no cover
                    f"no se pudo borrar el destino {paths.markdown_path}",
                    hint=str(exc),
                ) from exc
        else:
            raise IOError(
                f"el archivo de salida ya existe: {paths.markdown_path}",
                hint=(
                    "usá --force para sobrescribir o --suffix para versionar"
                ),
            )

    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover
        raise IOError(  # pragma: no cover
            f"no se pudo crear el directorio padre de {paths.markdown_path}",
            hint=str(exc),
        ) from exc

    _write_text(paths.markdown_path, markdown)
    return paths.markdown_path


def resolve_destination_collision(
    path: Path,
    *,
    force: bool,
    suffix: bool,
    kind: str = "path",
) -> Path:
    """Resuelve qué hacer si ``path`` ya existe (F8).

    - Si no existe → devuelve ``path`` tal cual.
    - Si existe + ``force=True`` → devuelve ``path`` (el caller lo borra
      antes de escribir).
    - Si existe + ``suffix=True`` → devuelve ``<stem>-N<ext>`` con el
      menor ``N >= 1`` que no exista en el directorio padre.
    - Si existe + sin flag → ``raise CapmdIOError(...)``.

    ``kind`` es decorativo (solo se usa en el mensaje de error):
    ``"dir"`` o ``"file"``.
    """
    if suffix and force:
        # Sanity guard: el caller debe haber validado, pero por defensa.
        raise ValueError("--suffix y --force son mutuamente excluyentes")

    if not path.exists():
        return path

    if force:
        return path

    if suffix:
        return _next_versioned_path(path, kind=kind)

    label = "directorio" if kind == "dir" else "archivo"
    raise IOError(
        f"el {label} de salida ya existe: {path}",
        hint=(
            "usá --force para sobrescribir o --suffix para versionar"
        ),
    )


def _next_versioned_path(path: Path, *, kind: str = "path") -> Path:
    """Devuelve ``<stem>-N<ext>`` con el menor ``N`` libre.

    Para files: ``out.md`` → ``out-1.md``.
    Para dirs: ``out/`` → ``out-1/`` (inserta antes del ``/`` final).
    Para extensions múltiples (``tar.gz``): el ``-N`` se inserta antes
    de la primera extensión. Casos raros como ``.gitignore`` (sin stem)
    caen a ``-1.gitignore`` (raro pero no rompe).
    """
    if kind == "dir" or path.name.endswith("/") or (path.is_dir() and not path.name.endswith("/")):
        # Directorio: stem es el nombre sin trailing slash; sin extensión.
        stem = path.name.rstrip("/")
        parent = path.parent
        n = 1
        while True:
            candidate = parent / f"{stem}-{n}"
            if not candidate.exists():
                return candidate
            n += 1
    # File: stem / suffix.
    stem = path.stem
    suffix_str = path.suffix
    parent = path.parent
    n = 1
    while True:
        candidate = parent / f"{stem}-{n}{suffix_str}"
        if not candidate.exists():
            return candidate
        n += 1


def _figure_to_dict(fig: Figure, images_dir_relative: str | None) -> dict[str, Any]:
    """Serializa una :class:`Figure` a dict para ``capmd.json``.

    El ``path`` se convierte a **relativo** (``images/fig-XX-NN.<ext>``)
    respecto al chapter dir para que el árbol sea portable.
    """
    name = fig.path.name
    relative = (
        f"{images_dir_relative.rstrip('/')}/{name}" if images_dir_relative else name
    )
    return {
        "chapter_index": fig.chapter_index,
        "index": fig.index,
        "path": relative,
        "page": fig.page,
        "bbox": list(fig.bbox) if fig.bbox is not None else None,
        "caption": fig.caption,
        "alt_text": fig.alt_text,
        "width": fig.width,
        "height": fig.height,
    }


def build_metadata(
    *,
    source: SourceDoc | None,
    stdin: bool,
    book_slug: str,
    chapter_slug: str,
    chapter: Chapter | None,
    page_range: PageRange | None,
    images_dir_relative: str | None,
    layout: str,
    title: str | None = None,
    cleaners_applied: tuple[str, ...] = (),
    cleaner_stats: tuple[dict[str, Any], ...] = (),
    figures: tuple[Figure, ...] = (),
    elapsed_seconds: float = 0.0,
    warnings: tuple[str, ...] = (),
    study_tags: tuple[str, ...] | None = None,
    reading_status: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    now: datetime | None = None,
) -> CapmdJsonV2:
    """Arma un :class:`CapmdJsonV2` (schema_version=2) con los timestamps correctos.

    ``title`` por default cae al ``book_slug`` (F3 resuelve antes con
    ``extract_first_h1`` → ``Chapter.title`` → ``book_slug``). ``now``
    es inyectable (tests deterministas). ``cleaner_stats`` y
    ``figures`` siempre son tuplas (vacias si no hay datos).

    Los kwargs ``study_*`` son opcionales (K2): si no se pasan o son
    neutrales, NO se emiten en el JSON. Si alguno diverge del neutro,
    se incluyen los 4 (mismo criterio que el front matter).
    """
    pages: tuple[int, ...] | None
    if page_range is not None:
        pages = page_range.pages
    elif chapter is not None:
        pages = tuple(range(chapter.start_page, chapter.end_page))
    else:
        pages = None

    chapter_payload: dict[str, Any] | None
    if chapter is not None:
        chapter_payload = {
            "index": chapter.index,
            "title": chapter.title,
            "level": chapter.level,
            "start_page": chapter.start_page,
            "end_page_inclusive": chapter.end_page_inclusive,
        }
    else:
        chapter_payload = None

    resolved_title = title if title is not None else (
        chapter.title if chapter is not None else book_slug
    )

    figure_dicts: tuple[dict[str, Any], ...] = tuple(
        _figure_to_dict(fig, images_dir_relative) for fig in figures
    )

    # Resolver los 4 campos study a valores neutrales si no se pasaron.
    resolved_tags = study_tags if study_tags is not None else ()
    resolved_status = reading_status if reading_status is not None else "unread"
    resolved_started = started_at
    resolved_finished = finished_at

    return CapmdJsonV2(
        book_slug=book_slug,
        chapter_slug=chapter_slug,
        title=resolved_title,
        source_file=None if stdin else (source.path.name if source else None),
        source_sha256=None if stdin else (source.sha256 if source else None),
        pages=pages,
        range_label=range_label_from(chapter=chapter, page_range=page_range),
        chapter=chapter_payload,
        generated_at=_now_iso(now),
        capmd_version=_capmd_version(),
        markitdown_version=markitdown_version(),
        images_dir=images_dir_relative,
        layout=layout,
        elapsed_seconds=elapsed_seconds,
        cleaner_stats=cleaner_stats,
        figures=figure_dicts,
        warnings=warnings,
        cleaners_applied=cleaners_applied,
        study_tags=tuple(resolved_tags),
        reading_status=resolved_status,
        started_at=resolved_started,
        finished_at=resolved_finished,
    )


def build_capmd_json_v2(**kwargs: Any) -> CapmdJsonV2:
    """Alias explícito de :func:`build_metadata` (F3 schema)."""
    return build_metadata(**kwargs)  # pragma: no cover


def _write_text(path: Path, content: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        raise IOError(  # pragma: no cover
            f"no se pudo escribir {path}",
            hint=str(exc),
        ) from exc
