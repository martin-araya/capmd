"""Lector de EPUB: spine + nav (fase C9).

Construye la lista de capítulos a partir del ``spine`` del EPUB y
extrae un único capítulo como archivo ``.xhtml`` temporal para que
``markitdown`` lo convierta.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ebooklib import ITEM_DOCUMENT, epub

from capmd.errors import SourceNotFound
from capmd.models import Chapter

__all__ = ["read_outline", "slice_epub"]


def _open_book(path: Path) -> Any:
    try:
        return epub.read_epub(str(path))
    except Exception as exc:
        raise SourceNotFound(
            f"no se pudo abrir el EPUB {path}: {exc}",
            hint="el archivo puede estar corrupto o no ser un EPUB válido",
        ) from exc


def _spine_chapter_idrefs(book: Any) -> list[str]:
    """Devuelve los idrefs del spine excluyendo el nav EPUB3.

    Cada idref corresponde a un item del manifest que es un capítulo
    real (no la página de navegación).
    """
    idrefs: list[str] = []
    for idref, _linear in book.spine:
        if idref == "nav":
            continue
        item = book.get_item_with_id(idref)
        if item is None:
            continue  # pragma: no cover
        # Filtrar por tipo DOCUMENT (los NCX no entran al spine, pero
        # por las dudas).
        if item.get_type() == ITEM_DOCUMENT:  # pragma: no cover
            idrefs.append(idref)
    return idrefs


def _toc_title_map(book: Any) -> dict[str, str]:
    """Mapea ``file_name`` → título del TOC.

    Recorre ``book.toc`` (lista de ``Link`` o ``Section``) y devuelve
    un dict para lookup rápido por nombre de archivo.
    """
    result: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, tuple):
            for child in node:  # pragma: no cover
                walk(child)  # pragma: no cover
            return  # pragma: no cover
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        # Link o Section: ambos tienen .title y .href (Section tiene
        # además sub-sections accesibles vía .subitems).
        title = getattr(node, "title", None)
        href = getattr(node, "href", None)
        if title and href:  # pragma: no cover
            result[href] = title
        sub = getattr(node, "subitems", None)  # pragma: no cover
        if sub:
            walk(sub)  # pragma: no cover

    walk(book.toc)
    return result


def read_outline(path: Path) -> list[Chapter]:
    """Lee el spine del EPUB y devuelve ``list[Chapter]``.

    El título de cada capítulo viene del TOC; si falta, usa el nombre
    del archivo XHTML o un fallback ``"Chapter N"``.
    """
    book = _open_book(path)
    idrefs = _spine_chapter_idrefs(book)
    titles_by_href = _toc_title_map(book)

    chapters: list[Chapter] = []
    for i, idref in enumerate(idrefs, start=1):
        item = book.get_item_with_id(idref)
        assert item is not None
        href = item.file_name
        title = titles_by_href.get(href) or item.file_name or f"Chapter {i}"
        chapters.append(
            Chapter(
                title=title,
                level=1,
                start_page=i,
                end_page=i + 1,
                index=i,
            )
        )
    return chapters


def slice_epub(src: Path, chapter: Chapter) -> Path:
    """Extrae el XHTML del capítulo a un archivo temporal ``.xhtml``.

    El caller es responsable de borrarlo en un ``finally``. Lanza
    :class:`SourceNotFound` si el EPUB está corrupto.
    """
    book = _open_book(src)
    idrefs = _spine_chapter_idrefs(book)
    if chapter.index < 1 or chapter.index > len(idrefs):
        raise ValueError(f"índice {chapter.index} fuera de rango (spine tiene {len(idrefs)})")
    idref = idrefs[chapter.index - 1]
    item = book.get_item_with_id(idref)
    assert item is not None
    content = item.get_content()

    fd, tmp_path = tempfile.mkstemp(suffix=".html")
    try:
        with open(fd, "wb") as fh:
            fh.write(content)
    except Exception:  # pragma: no cover
        Path(tmp_path).unlink(missing_ok=True)  # pragma: no cover
        raise  # pragma: no cover

    return Path(tmp_path)
