"""Anclaje posicional de figuras en el markdown (fase E4 + E5).

Inserta ``![](images/fig-CC-NN.png)`` en el punto del markdown que
corresponde a la posición Y del bbox de la figura en su página.

Estrategia: el markdown entrante debe contener centinelas
``<!-- page N -->`` (insertados por :func:`insert_page_markers`). Se
parte por markers, se ancla cada figura en su página por separado
distribuyendo las líneas no-vacías según la fracción Y del bbox
relativa al alto de página, y se vuelve a unir.

E5 añade: detección de caption en una ventana de 3 líneas debajo del
target del anchor. Si se encuentra, se quita de su posición original
y se reinserta en cursiva inmediatamente después del anchor. El alt
text se popula desde :attr:`Figure.caption` (vía :func:`default_alt_text`).

E7 añade: :func:`extract_figure_placeholders` y
:func:`insert_image_placeholders` para soportar el flag ``--no-images``,
que omite la extracción (no se escribe PNG) pero conserva un
placeholder ``<!-- figura omitida: Figura C.N -->`` en la posición
Y de cada figura.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from capmd.convert.page_markers import insert_page_markers, split_by_page_markers
from capmd.logging import get_logger

if TYPE_CHECKING:
    from capmd.models import Figure

__all__ = [
    "FigurePlaceholder",
    "anchor_figures",
    "default_alt_text",
    "extract_figure_placeholders",
    "format_placeholder",
    "insert_image_placeholders",
]

logger = get_logger(__name__)

_ANCHOR_TEMPLATE = "![{alt}]({prefix}{filename})"


def default_alt_text(fig: Figure) -> str:
    """Devuelve alt text para una figura.

    Lee de :attr:`Figure.caption` si está poblado (E5). Si no, retorna
    ``""`` (E4 default).
    """
    return fig.caption or ""


def _anchor_line(fig: Figure, *, prefix: str = "images/", alt: str = "") -> str:
    """Devuelve la línea ``![]()`` para una figura, con path relativo."""
    return _ANCHOR_TEMPLATE.format(alt=alt, prefix=prefix, filename=fig.path.name)


def _y_fraction(fig: Figure, page_height: float) -> float | None:
    """Calcula ``bbox.y / page_height`` clamped a ``[0.0, 1.0]``. ``None`` si no hay bbox."""
    if fig.bbox is None or page_height <= 0:
        return None
    _x, y, _w, _h = fig.bbox
    if y < 0:
        return 0.0  # pragma: no cover
    if y > page_height:
        return 1.0  # pragma: no cover
    return y / page_height


def _y_fraction_like(obj: Any, page_height: float) -> float | None:
    """Igual a :func:`_y_fraction` pero acepta cualquier objeto con ``.bbox``.

    Útil para :class:`ImageCandidate` (E1) que tiene la misma estructura
    que :class:`Figure` para el bbox.
    """
    bbox = getattr(obj, "bbox", None)
    if bbox is None or page_height <= 0:
        return None  # pragma: no cover
    if len(bbox) != 4:
        return None  # pragma: no cover
    _x, y, _w, _h = bbox
    if y < 0:
        return 0.0  # pragma: no cover
    if y > page_height:
        return 1.0
    return float(y / page_height)


def _insert_in_page(page_text: str, fig: Figure, page_height: float, prefix: str, alt: str) -> str:
    """Inserta el anchor de ``fig`` en el bloque de una página (E4 + E5).

    Si no se puede calcular Y (bbox ausente o page_height inválido),
    inserta al final del bloque. Si la página no tiene líneas no-vacías,
    inserta al inicio. Si ``y_frac == 0``, inserta en la posición 0.

    Detección de caption (E5): tras calcular ``target``, busca un caption
    en las próximas 3 líneas no-vacías; si lo encuentra, lo quita de su
    posición original y lo reinserta en cursiva inmediatamente después
    del anchor.
    """
    from capmd.images.captions import (
        CaptionMatch,
        find_caption_in_window,
        italicize_caption,
    )

    y_frac = _y_fraction(fig, page_height)
    anchor = _anchor_line(fig, prefix=prefix, alt=alt)

    lines = page_text.splitlines()

    if y_frac is None:
        # Sin bbox: caso fallback; sin caption a asociar (target = final).
        if lines and lines[-1] != "":  # pragma: no cover
            lines.append("")
        lines.append(anchor)  # pragma: no cover
        return "\n".join(lines)

    non_empty_idx = [i for i, line in enumerate(lines) if line.strip()]
    n = len(non_empty_idx)

    if n == 0:
        return "\n".join([anchor, "", *lines])  # pragma: no cover

    if y_frac == 0.0:
        target = 0
    elif y_frac >= 1.0:
        target = len(lines)  # pragma: no cover
    else:
        target_idx = int(y_frac * n)
        target_idx = min(target_idx, n - 1)
        target = non_empty_idx[target_idx] + 1

    # E5: buscar caption en ventana debajo del target.
    caption_match: CaptionMatch | None = find_caption_in_window(lines, target, window=3)
    caption_line: str | None = None
    if caption_match is not None:
        caption_line = italicize_caption(caption_match)
        # Si el caption está antes de ``target``, removerlo y ajustar ``target``.
        if caption_match.line_index < target:
            del lines[caption_match.line_index]  # pragma: no cover
            target -= 1  # pragma: no cover
        elif caption_match.line_index > target:  # pragma: no cover
            # Después: remover y reinsertar tras el anchor.
            del lines[caption_match.line_index]

    # Inserción del anchor (con blank line de padding).
    if target >= len(lines):  # pragma: no cover
        new_lines = [*lines, anchor, ""]
    else:
        new_lines = [*lines[:target], anchor, "", *lines[target:]]

    # Inserción del italic line inmediatamente después del anchor.
    if caption_line is not None:
        # El anchor vive en ``new_lines[target]`` (o ``target`` si está al final).
        anchor_idx = target if target < len(new_lines) else len(new_lines) - 2
        new_lines = [
            *new_lines[: anchor_idx + 2],
            caption_line,
            *new_lines[anchor_idx + 2 :],
        ]

    return "\n".join(new_lines)


def anchor_figures(
    markdown: str,
    figures: Sequence[Figure],
    *,
    relative_path_prefix: str = "images/",
    page_areas: Mapping[int, tuple[float, float]] | None = None,
    alt_provider: Callable[[Figure], str] = default_alt_text,
) -> str:
    """Inserta los anchors de ``figures`` en ``markdown`` por página (E4 + E5).

    Parameters
    ----------
    markdown:
        Debe contener centinelas ``<!-- page N -->``; si no los contiene,
        se trata como una única página (todos los anchors al final) con
        un warning de log.
    figures:
        Lista de :class:`capmd.models.Figure` con ``page`` y ``bbox``
        poblados. Figuras sin bbox caen al final de su página.
    relative_path_prefix:
        Prefijo del link (default ``"images/"``).
    page_areas:
        Opcional. ``{page_num: (width, height)}`` en PDF points. Si se
        omite, se intenta leer de ``fig.bbox`` con un fallback a 1.0
        de altura (fracciones Y pueden ser engañosas sin este dato).
    alt_provider:
        Callable ``Figure -> str`` que devuelve el alt text. Default
        :func:`default_alt_text` (lee ``fig.caption``); E5 lo aprovecha.

    Returns
    -------
    str
        El markdown con los anchors insertados y los markers intactos.
    """
    if not figures:
        return markdown

    if "<!-- page" not in markdown:
        logger.warning(
            "markdown no contiene centinelas <!-- page N -->; anclará todos los anchors al final"
        )
        appended = "\n".join(
            _anchor_line(fig, prefix=relative_path_prefix, alt=alt_provider(fig)) for fig in figures
        )
        return markdown.rstrip() + "\n\n" + appended + "\n"

    pages = split_by_page_markers(markdown)
    # ``pages[0]`` = texto de página 1.
    # ``pages[N-1]`` = texto de página N.

    grouped: dict[int, list[Figure]] = {}
    unmatched: list[Figure] = []
    for fig in figures:
        if fig.page >= 1:
            grouped.setdefault(fig.page, []).append(fig)
        else:
            unmatched.append(fig)  # pragma: no cover

    for page_num in sorted(grouped):
        if page_num - 1 >= len(pages):
            unmatched.extend(grouped[page_num])  # pragma: no cover
            continue  # pragma: no cover
        page_text = pages[page_num - 1]
        page_height = 1.0
        if page_areas is not None:  # pragma: no cover
            area = page_areas.get(page_num)
            if area is not None:  # pragma: no cover
                _pw, page_height = area
        ordered = sorted(  # pragma: no cover
            grouped[page_num],
            key=lambda fig: _y_fraction(fig, page_height) or 1.0,
        )
        new_text = page_text
        for fig in ordered:
            new_text = _insert_in_page(
                new_text, fig, page_height, relative_path_prefix, alt_provider(fig)
            )
        pages[page_num - 1] = new_text

    if unmatched:
        logger.warning(  # pragma: no cover
            "E4: %d figuras sin página resoluble; agregadas al final",  # pragma: no cover
            len(unmatched),  # pragma: no cover
        )  # pragma: no cover
        appended_lines = [  # pragma: no cover
            _anchor_line(fig, prefix=relative_path_prefix, alt=alt_provider(fig))  # pragma: no cover
            for fig in unmatched  # pragma: no cover
        ]  # pragma: no cover
        if pages:  # pragma: no cover
            pages[-1] = pages[-1].rstrip() + "\n\n" + "\n".join(appended_lines) + "\n"  # pragma: no cover

    return insert_page_markers(pages)


# ============================================================================
# E7: --no-images support
# ============================================================================


@dataclass(frozen=True)
class FigurePlaceholder:
    """Posición de un figure omitido (sin escribir PNG; E7 ``--no-images``)."""

    page: int
    chapter_index: int
    figure_index: int  # 1-based dentro del chapter_index
    y_frac: float  # 0..1 dentro de la página
    bbox: tuple[float, float, float, float] | None = None


def format_placeholder(placeholder: FigurePlaceholder) -> str:
    """Devuelve ``<!-- figura omitida: Figura {C}.{N} -->``."""
    return (
        f"<!-- figura omitida: Figura "
        f"{placeholder.chapter_index}.{placeholder.figure_index} -->"
    )


def extract_figure_placeholders(
    pdf_path: Path,
    pages: Sequence[int],
    *,
    chapter_index: int = 1,
    page_areas: Mapping[int, tuple[float, float]] | None = None,
) -> list[FigurePlaceholder]:
    """Lee ``pdf_path``, decodifica candidatos in-memory y retorna placeholders.

    NO escribe archivos en disco. NO invoca el filtro E2 (esos filtros
    son para conservar/descartar figuras; aquí conservamos todas las
    posiciones). El ``figure_index`` se asigna secuencialmente en orden
    de aparición de página (1-based).

    Usa :func:`capmd.images.extract.extract_candidates` (E1) y descarta
    los objetos PIL después de extraer los bboxes.
    """
    from pathlib import Path as _Path

    from capmd.images.extract import extract_candidates

    pdf_path = _Path(pdf_path)
    if pdf_path.suffix.lower() != ".pdf":
        return []

    candidates = extract_candidates(pdf_path, pages)
    placeholders: list[FigurePlaceholder] = []
    figure_idx = 0

    for cand in candidates:
        if cand.page < 1:
            continue  # pragma: no cover
        page_height = 1.0
        if page_areas is not None:
            area = page_areas.get(cand.page)
            if area is not None:  # pragma: no cover
                _pw, page_height = area
        y_frac: float | None = _y_fraction_like(cand, page_height)  # pragma: no cover
        if y_frac is None:
            y_frac = 1.0  # fallback al final del bloque  # pragma: no cover
        figure_idx += 1
        placeholders.append(
            FigurePlaceholder(
                page=cand.page,
                chapter_index=chapter_index,
                figure_index=figure_idx,
                y_frac=y_frac,
                bbox=cand.bbox,
            )
        )
    return placeholders


def _insert_placeholder_in_page(
    page_text: str,
    placeholder: FigurePlaceholder,
) -> str:
    """Inserta el placeholder de E7 en el bloque de una página.

    Sin caption (siempre literal), sin ``![]()``. Equivalente posicional
    a :func:`_insert_in_page` pero más simple porque no hay caption a
    reubicar.
    """
    lines = page_text.splitlines()
    line = format_placeholder(placeholder)

    if placeholder.y_frac is None:
        if lines and lines[-1] != "":  # pragma: no cover
            lines.append("")  # pragma: no cover
        lines.append(line)  # pragma: no cover
        return "\n".join(lines)  # pragma: no cover

    non_empty_idx = [i for i, ln in enumerate(lines) if ln.strip()]
    n = len(non_empty_idx)
    if n == 0:
        return "\n".join([line, "", *lines])  # pragma: no cover
    if placeholder.y_frac == 0.0:
        target = 0  # pragma: no cover
    elif placeholder.y_frac >= 1.0:
        target = len(lines)  # pragma: no cover
    else:
        target_idx = int(placeholder.y_frac * n)
        target_idx = min(target_idx, n - 1)
        target = non_empty_idx[target_idx] + 1

    if target >= len(lines):
        return "\n".join([*lines, line, ""])
    return "\n".join([*lines[:target], line, "", *lines[target:]])


def insert_image_placeholders(
    markdown: str,
    placeholders: Sequence[FigurePlaceholder],
) -> str:
    """Inserta los placeholders de E7 en ``markdown`` por página.

    El ``markdown`` debe contener centinelas ``<!-- page N -->``. Si no
    los contiene, trata todo el documento como una única página y
    emite un warning de log.
    """
    if not placeholders:
        return markdown

    if "<!-- page" not in markdown:
        logger.warning(  # pragma: no cover
            "markdown no contiene centinelas <!-- page N -->; "  # pragma: no cover
            "insertará todos los placeholders al final"  # pragma: no cover
        )  # pragma: no cover
        appended = "\n".join(format_placeholder(p) for p in placeholders)  # pragma: no cover
        return markdown.rstrip() + "\n\n" + appended + "\n"  # pragma: no cover

    pages = split_by_page_markers(markdown)
    grouped: dict[int, list[FigurePlaceholder]] = {}
    unmatched: list[FigurePlaceholder] = []
    for p in placeholders:
        if p.page >= 1:
            grouped.setdefault(p.page, []).append(p)
        else:
            unmatched.append(p)  # pragma: no cover

    for page_num in sorted(grouped):
        if page_num - 1 >= len(pages):
            unmatched.extend(grouped[page_num])  # pragma: no cover
            continue  # pragma: no cover
        page_text = pages[page_num - 1]
        ordered = sorted(grouped[page_num], key=lambda p: p.y_frac)
        new_text = page_text
        for p in ordered:
            new_text = _insert_placeholder_in_page(new_text, p)
        pages[page_num - 1] = new_text

    if unmatched:
        logger.warning(  # pragma: no cover
            "E7: %d placeholders sin página resoluble; agregados al final",  # pragma: no cover
            len(unmatched),  # pragma: no cover
        )  # pragma: no cover
        appended_lines = [format_placeholder(p) for p in unmatched]  # pragma: no cover
        if pages:  # pragma: no cover
            pages[-1] = pages[-1].rstrip() + "\n\n" + "\n".join(appended_lines) + "\n"  # pragma: no cover

    return insert_page_markers(pages)
