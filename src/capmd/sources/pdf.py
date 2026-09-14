"""Lector de PDF: outline/TOC (fases C1, C3) y slicing (fase C4).

El aplanamiento del outline de ``pypdf`` a ``list[Chapter]`` (C1), la
inferencia de ``end_page`` a partir de la lista DFS y el total de
páginas (C3), y el recorte de páginas a un PDF temporal con
``pypdf.PdfWriter`` (C4). El orden del outline es siempre DFS, los
``start_page`` son 1-indexed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from capmd.errors import SourceNotFound
from capmd.logging import get_logger
from capmd.models import Chapter, PageRange

__all__ = [
    "OutlineEntry",
    "infer_ranges",
    "read_outline",
    "read_outline_tuples",
    "read_outline_with_fallback",
    "slice_pdf",
]

logger = get_logger(__name__)

# Tupla ``(level, title, page)`` que pide el roadmap literal de C1.
OutlineEntry = tuple[int, str, int]

OutlineNode = list["OutlineNode"] | dict[str, Any] | str


def _open_reader(path: Path) -> PdfReader:
    """Abre el PDF o lanza ``SourceNotFound`` con mensaje humano."""
    try:
        return PdfReader(str(path))
    except FileNotFoundError as exc:
        raise SourceNotFound(
            f"el archivo {path} no existe",
            hint="verificá la ruta y que el archivo sea legible",
        ) from exc
    except PdfReadError as exc:
        raise SourceNotFound(
            f"no se pudo leer el PDF {path}: {exc}",
            hint="el archivo puede estar corrupto o encriptado",
        ) from exc


def _resolve_page(reader: PdfReader, item: OutlineNode) -> int | None:
    """Resuelve la página (1-indexed) de una entrada del outline.

    ``None`` significa "no se pudo resolver"; el caller descarta la
    entrada y avisa. ``pypdf`` devuelve páginas 0-indexadas; acá se
    devuelve 1-indexada para alinear con el resto de capmd.

    pypdf tipifica ``get_destination_page_number`` como ``(Destination) -> int``
    pero en runtime acepta tanto un dict (formato moderno) como un
    ``str`` (named destination legacy). Hacemos cast explícito.
    """
    raw: int | None
    if isinstance(item, (str, dict)):
        try:
            raw = reader.get_destination_page_number(cast(Any, item))
        except Exception:
            return None
    else:
        return None
    if raw is None:
        return None
    return int(raw) + 1


def _walk(
    nodes: list[OutlineNode],
    reader: PdfReader,
    depth: int,
    out: list[Chapter],
) -> None:
    """Recorre el outline recursivamente y apila :class:`Chapter`.

    ``depth=0`` produce ``level=1`` (raíz del outline); cada nivel
    anidado incrementa ambos.
    """
    level = depth + 1
    for node in nodes:
        if isinstance(node, list):
            _walk(node, reader, depth + 1, out)
            continue
        if not isinstance(node, (str, dict)):
            logger.warning("outline: descartando entrada de tipo %s", type(node).__name__)
            continue

        title: str | None
        if isinstance(node, dict):
            raw = node.get("/Title")
            title = str(raw) if raw is not None else None
        else:
            title = node

        if not title:
            logger.warning("outline: descartando entrada sin título")
            continue

        page = _resolve_page(reader, node)
        if page is None or page < 1:
            logger.warning("outline: descartando %r (página no resoluble)", title)
            continue

        out.append(
            Chapter(
                title=title,
                level=level,
                start_page=page,
                # Provisional: la inferencia de end_page es C3.
                end_page=page,
                index=len(out) + 1,
            )
        )


def read_outline(path: Path) -> list[Chapter]:
    """Lee el outline del PDF en ``path`` y lo devuelve aplanado.

    El orden es el de aparición en el outline (DFS). Las páginas son
    1-indexed. Entradas inválidas se descartan con un warning.

    ``end_page`` queda igual a ``start_page``; la inferencia real la
    hace la fase C3.
    """
    reader = _open_reader(path)
    outline = reader.outline or []
    if not outline:
        return []

    chapters: list[Chapter] = []
    _walk(cast(list[OutlineNode], outline), reader, depth=0, out=chapters)
    return chapters


def read_outline_tuples(path: Path) -> list[OutlineEntry]:
    """Variante tupla ``(level, title, page)`` que pide el roadmap C1."""
    return [(c.level, c.title, c.start_page) for c in read_outline(path)]


def read_outline_with_fallback(path: Path) -> list[Chapter]:
    """Lee el outline; si está vacío, cae a la heurística (C8).

    Propaga :class:`ChapterDetectionFailed` si la heurística tampoco
    encuentra capítulos. La firma es idéntica a :func:`read_outline`
    para que el caller (CLI de ``toc`` y ``--chapter``) pueda
    intercambiarla sin condicionales.
    """
    chapters = read_outline(path)
    if chapters:
        return chapters

    from capmd.sources.heuristic import detect_chapters

    return detect_chapters(path)


def infer_ranges(chapters: list[Chapter], total_pages: int) -> list[Chapter]:
    """Devuelve una nueva lista con ``end_page`` corregido en cada entrada.

    Regla (half-open, ``end_page`` exclusivo):
      Una entrada ``e`` en posición ``i`` extiende hasta ``start_page``
      de la próxima entrada ``j > i`` con ``level[j] <= level[i]`` (un
      hermano o un ancestro). Si no existe tal ``j``, llega hasta
      ``total_pages + 1``.

    Resultado: los rangos de nivel 1 son contiguos, sin solapes y sin
    huecos; las sub-entradas quedan anidadas dentro de su ancestro.

    Validaciones:
      - ``total_pages >= 1``.
      - Si la última entrada tiene ``start_page > total_pages``, se
        lanza ``ValueError`` (outline corrupto: apunta más allá del
        documento).
    """
    if total_pages < 1:
        raise ValueError(f"total_pages must be >= 1, got {total_pages}")

    if not chapters:
        return []

    if chapters[-1].start_page > total_pages:
        raise ValueError(
            f"el outline apunta más allá del documento: última entrada en "
            f"página {chapters[-1].start_page}, documento tiene {total_pages}"
        )

    n = len(chapters)
    end_pages: list[int] = [0] * n
    # Para cada i: buscar la próxima j > i con level[j] <= level[i];
    # si no existe, total_pages + 1. O(N^2) en el peor caso pero las
    # listas de outline tienen típicamente < 1000 entradas.
    for i in range(n - 1, -1, -1):
        closer = total_pages + 1
        for j in range(i + 1, n):
            if chapters[j].level <= chapters[i].level:
                closer = chapters[j].start_page
                break
        end_pages[i] = closer

    return [
        Chapter(
            title=c.title,
            level=c.level,
            start_page=c.start_page,
            end_page=ep,
            index=c.index,
        )
        for c, ep in zip(chapters, end_pages, strict=True)
    ]


def slice_pdf(src: Path, pages: PageRange) -> Path:
    """Escribe un PDF temporal con solo las páginas de ``pages`` y devuelve su ruta.

    El caller es responsable de borrar el archivo (típicamente en un
    ``finally`` con ``unlink(missing_ok=True)``). El temporal vive en
    el directorio del sistema (``tempfile.gettempdir()``).

    ``pages`` viene 1-indexed; pypdf trabaja 0-indexed, así que se
    resta 1 al construir el writer. La unicidad y el orden ya están
    garantizados por :class:`PageRange`.
    """
    try:
        reader = PdfReader(str(src))
    except (FileNotFoundError, PdfReadError) as exc:
        raise SourceNotFound(
            f"no se pudo abrir {src}: {exc}",
            hint="el archivo puede estar corrupto o encriptado",
        ) from exc

    writer = PdfWriter()
    for page_num in pages.pages:
        writer.add_page(reader.pages[page_num - 1])

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with open(fd, "wb") as fh:
            writer.write(fh)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    return Path(tmp_path)
