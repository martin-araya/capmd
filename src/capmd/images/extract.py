"""Extracción y filtrado de imágenes embebidas en PDFs (fases E1 + E2).

API pública:

- :class:`ImageCandidate`: representación in-memory de una imagen extraída
  con su metadata posicional, antes de cualquier filtro (E2).
- :class:`ExtractResult`: dataclass con ``figures`` y ``report`` (E2).
- :class:`ExtractOptions`: opciones inmutables (formato, max_width).
- :func:`extract_candidates`: decodifica todas las imágenes embebidas de un
  set de páginas y las devuelve en memoria (sin escribir, sin filtrar).
- :func:`write_figures`: persiste una lista de :class:`ImageCandidate` ya
  filtrada a una carpeta con nombres ``fig-NNN.<ext>``.
- :func:`extract_figures`: atajo que orquesta ``extract_candidates`` →
  :func:`capmd.images.filter.filter_candidates` → ``write_figures`` con
  los :class:`FilterRules` dados.

E3 (nombres por capítulo), E4 (anclaje posicional), E5 (captions) y E7
(``--no-images``) consumen :class:`ExtractResult`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pypdfium2 as pdfium
from PIL import Image

from capmd.images.filter import FilterReport, FilterRules, filter_candidates
from capmd.models import Figure

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "SUPPORTED_IMAGE_FORMATS",
    "ExtractOptions",
    "ExtractResult",
    "ImageCandidate",
    "extract_candidates",
    "extract_figures",
    "make_figure_name",
    "write_figures",
]

# Constante raw de PDFium (FPDF_PAGEOBJ_IMAGE). Mismo valor en todas las
# versiones de PDFium; lo usamos en vez de importar pypdfium2.raw para
# no acoplarnos a layout internos de la lib.
_PAGEOBJ_IMAGE: int = 3

# Filtros PIL nombrados (string → constante).
_PIL_LANCZOS = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", 1))

SUPPORTED_IMAGE_FORMATS: frozenset[str] = frozenset({"png", "webp"})


@dataclass(frozen=True)
class ExtractOptions:
    """Opciones inmutables para una corrida de extracción (E1)."""

    image_format: str = "png"
    max_width: int | None = None

    def __post_init__(self) -> None:
        if self.image_format not in SUPPORTED_IMAGE_FORMATS:
            raise ValueError(
                f"formato no soportado: {self.image_format!r} "
                f"(válidos: {sorted(SUPPORTED_IMAGE_FORMATS)})"
            )
        if self.max_width is not None and self.max_width <= 0:
            raise ValueError(f"max_width debe ser > 0, recibido: {self.max_width}")


@dataclass(frozen=True)
class ImageCandidate:
    """Imagen decodificada en memoria con su metadata posicional."""

    image: Image.Image
    page: int
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class ExtractResult:
    """Salida completa de :func:`extract_figures` (E2)."""

    figures: list[Figure]
    report: FilterReport


def _iter_image_objects(page: pdfium.PdfPage) -> list[Any]:
    """Devuelve la lista de objetos de tipo imagen en ``page``.

    El orden lo define PDFium y es estable para una misma entrada y
    versión de pypdfium2 — necesario para que los nombres de archivo
    sean deterministas (E3).
    """
    try:
        objects = list(page.get_objects())
    except Exception:
        return []
    return [obj for obj in objects if getattr(obj, "type", None) == _PAGEOBJ_IMAGE]


def _get_object_bitmap(obj: Any) -> Image.Image | None:
    """Renderiza un objeto de página a una :class:`PIL.Image.Image`.

    Intenta primero :meth:`PdfPageObject.get_bitmap` (pypdfium2 v5+).
    Si la versión instalada no lo expone, devuelve ``None`` y el caller
    cae al fallback de render recortado.
    """
    get_bitmap = getattr(obj, "get_bitmap", None)
    if get_bitmap is None:
        return None
    try:
        bitmap = get_bitmap(render=True)
    except Exception:
        return None
    try:
        result: Image.Image | None = bitmap.to_pil()
        return result
    except Exception:
        return None


def _get_object_bitmap_via_clip(
    page: pdfium.PdfPage, obj: Any, scale: float = 2.0
) -> Image.Image | None:
    """Fallback: renderiza el área del objeto cuando ``get_bitmap`` no está disponible."""
    get_bounds = getattr(obj, "get_bounds", None)
    if get_bounds is None:
        return None
    try:
        bounds = get_bounds()
    except Exception:
        return None
    if not bounds or len(bounds) != 4:
        return None
    x, y, w, h = bounds
    if w <= 0 or h <= 0:
        return None
    try:
        bitmap = page.render(
            clip=(float(x), float(y), float(x + w), float(y + h)),
            scale=float(scale),
        )
    except Exception:
        return None
    try:
        result: Image.Image | None = bitmap.to_pil()
        return result
    except Exception:
        return None


def _get_object_bounds(obj: Any) -> tuple[float, float, float, float] | None:
    """Lee el bbox del objeto si está disponible, normalizado a tuple[float, ...]."""
    get_bounds = getattr(obj, "get_bounds", None)
    if get_bounds is None:
        return None
    try:
        raw = tuple(get_bounds())
    except Exception:
        return None
    if len(raw) != 4:
        return None
    return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))


def make_figure_name(chapter_index: int, figure_index: int, ext: str) -> str:
    """Devuelve ``fig-{chapter:02d}-{idx:02d}.{ext}``.

    El padding escala automáticamente a 3+ dígitos cuando el número lo
    requiere (``fig-100-01.png`` para chapter 100, ``fig-03-100.png``
    para figura 100). Coincide con el ejemplo literal del roadmap
    (``fig-03-01.png`` para capítulo 3, figura 1).
    """
    if chapter_index < 1:
        raise ValueError(f"chapter_index debe ser >= 1, recibido: {chapter_index}")
    if figure_index < 1:
        raise ValueError(f"figure_index debe ser >= 1, recibido: {figure_index}")
    return f"fig-{chapter_index:02d}-{figure_index:02d}.{ext}"


def _save_image(image: Image.Image, target: Path, image_format: str) -> None:
    """Escribe ``image`` en ``target`` con encoding byte-determinista (E3).

    Limpia ``info`` (Pillow: tEXt/comment chunks) antes de guardar y
    pasa opciones explícitas sin metadata volátil para WebP. PNG no
    escribe ``tIME`` por default en Pillow; limpiamos ``info`` igual
    por defensa.
    """
    clean = image.copy()
    clean.info = {}
    if image_format == "png":
        clean.save(target, format="PNG", optimize=False)
    else:  # "webp"
        clean.save(
            target,
            format="WEBP",
            quality=90,
            exif=b"",
            icc_profile=None,
        )


def _downscale_if_needed(image: Image.Image, max_width: int | None) -> Image.Image:
    """Si ``max_width`` está definido y la imagen lo supera, reescala con LANCZOS."""
    if max_width is None or image.width <= max_width:
        return image
    ratio = max_width / float(image.width)
    new_height = max(1, round(image.height * ratio))
    return image.resize((max_width, new_height), _PIL_LANCZOS)


_DEFAULT_OPTIONS = ExtractOptions()
_DEFAULT_RULES = FilterRules()


def extract_candidates(
    pdf_path: Path,
    pages: Sequence[int],
    *,
    max_width: int | None = None,
) -> list[ImageCandidate]:
    """Decodifica TODAS las imágenes embebidas de ``pages`` y las devuelve en memoria.

    No escribe a disco. No aplica filtros. Orden preservado según el orden
    de aparición de páginas y, dentro de cada página, el orden de los
    objetos de tipo imagen reportados por pypdfium2.

    Si ``max_width`` está definido, las imágenes que lo superan se
    reescalan con LANCZOS preservando aspect ratio antes de devolver
    (coincide con el tamaño final que tendrá el archivo escrito).
    """
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"solo se extraen imágenes de PDF, recibido: {pdf_path.suffix!r}")
    if max_width is not None and max_width <= 0:
        raise ValueError(f"max_width debe ser > 0, recibido: {max_width}")

    ordered = sorted({int(p) for p in pages if int(p) >= 1})
    candidates: list[ImageCandidate] = []

    if not ordered:
        return candidates

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        total = len(pdf)
        for page_num in ordered:
            if page_num > total:
                continue
            page = pdf[page_num - 1]
            for obj in _iter_image_objects(page):
                image = _get_object_bitmap(obj)
                if image is None:
                    image = _get_object_bitmap_via_clip(page, obj)
                if image is None:
                    continue
                if max_width is not None:
                    image = _downscale_if_needed(image, max_width)
                candidates.append(
                    ImageCandidate(
                        image=image,
                        page=page_num,
                        bbox=_get_object_bounds(obj),
                    )
                )
    finally:
        with contextlib.suppress(Exception):
            pdf.close()

    return candidates


def _collect_page_areas(pdf_path: Path, pages: Sequence[int]) -> Mapping[int, tuple[float, float]]:
    """Devuelve ``{page_num: (width, height)}`` en PDF points para ``pages``.

    Las páginas que no se pueden leer se omiten silenciosamente; el
    filtro de BACKGROUND las trata como si su área fuera desconocida
    (no descarta por cobertura).
    """
    ordered = sorted({int(p) for p in pages if int(p) >= 1})
    if not ordered:
        return {}
    areas: dict[int, tuple[float, float]] = {}
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        total = len(pdf)
        for page_num in ordered:
            if page_num > total:
                continue
            try:
                size = pdf[page_num - 1].get_size()
            except Exception:
                continue
            if isinstance(size, tuple) and len(size) == 2:
                areas[page_num] = (float(size[0]), float(size[1]))
    finally:
        with contextlib.suppress(Exception):
            pdf.close()
    return areas


def write_figures(
    candidates: Sequence[ImageCandidate],
    out_dir: Path,
    *,
    image_format: str = "png",
    chapter_index: int = 1,
) -> list[Figure]:
    """Escribe los ``candidates`` a ``out_dir`` con nombres ``fig-NNN.<ext>``.

    Crea ``out_dir`` con padres. Saltar silenciosamente errores de
    escritura individuales (permisos, etc.). Devuelve un :class:`Figure`
    por candidato escrito, en orden secuencial con índice global.
    """
    if image_format not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(
            f"formato no soportado: {image_format!r} (válidos: {sorted(SUPPORTED_IMAGE_FORMATS)})"
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    figures: list[Figure] = []
    idx = 0
    for cand in candidates:
        idx += 1
        target = out_dir / make_figure_name(chapter_index, idx, image_format)
        try:
            _save_image(cand.image, target, image_format)
        except Exception:
            idx -= 1
            continue
        figures.append(
            Figure(
                chapter_index=chapter_index,
                index=idx,
                path=target,
                page=cand.page,
                bbox=cand.bbox,
                width=cand.image.width,
                height=cand.image.height,
            )
        )
    return figures


def extract_figures(
    pdf_path: Path,
    pages: Sequence[int],
    out_dir: Path,
    *,
    options: ExtractOptions = _DEFAULT_OPTIONS,
    rules: FilterRules = _DEFAULT_RULES,
    chapter_index: int = 1,
) -> ExtractResult:
    """Atajo que aplica el pipeline E1+E2 sobre ``pages``.

    Equivale a:

    1. ``extract_candidates(pdf_path, pages, max_width=options.max_width)``
    2. ``filter_candidates(candidates, page_areas, rules)``
    3. ``write_figures(report.kept, out_dir, image_format=options.image_format)``

    Devuelve un :class:`ExtractResult` con la lista de :class:`Figure`
    persistidos y el :class:`FilterReport` con los descartados.
    """
    if options.image_format not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(
            f"formato no soportado: {options.image_format!r} "
            f"(válidos: {sorted(SUPPORTED_IMAGE_FORMATS)})"
        )
    if options.max_width is not None and options.max_width <= 0:
        raise ValueError(f"max_width debe ser > 0, recibido: {options.max_width}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"solo se extraen imágenes de PDF, recibido: {pdf_path.suffix!r}")

    candidates = extract_candidates(pdf_path, pages, max_width=options.max_width)
    page_areas = _collect_page_areas(pdf_path, pages)
    report = filter_candidates(candidates, page_areas, rules)
    figures = write_figures(
        report.kept,
        out_dir,
        image_format=options.image_format,
        chapter_index=chapter_index,
    )
    return ExtractResult(figures=figures, report=report)
