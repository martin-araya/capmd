"""Filtros de "basura" aplicados a las imágenes extraídas (fase E2).

Tres filtros puros, sin estado, sin I/O:

- :class:`FilterDecision.TOO_SMALL` descarta imágenes por debajo de un
  tamaño mínimo en píxeles (anchura y altura independientes).
- :class:`FilterDecision.BACKGROUND` descarta imágenes cuyo bbox
  cubre casi toda la página (umbral por cobertura).
- :class:`FilterDecision.LOGO_REPEATED` descarta repeticiones de un
  mismo hash que aparece en una fracción demasiado alta de las páginas
  observadas (la PRIMERA aparición se conserva como referencia).

El orden de evaluación es TOO_SMALL → BACKGROUND → LOGO_REPEATED. La
primera aparición de cada hash se evalúa contra los dos primeros antes
de participar en el agrupamiento por repetición.

Las funciones operan sobre :class:`capmd.images.extract.ImageCandidate`
y un mapping de áreas de página. No tocan el PDF ni el filesystem.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capmd.images.extract import ImageCandidate

__all__ = ["FilterDecision", "FilterReport", "FilterRules", "filter_candidates"]


class FilterDecision(str, Enum):
    """Razones por las que un candidato se conserva o se descarta."""

    KEPT = "kept"
    TOO_SMALL = "too_small"
    LOGO_REPEATED = "logo_repeated"
    BACKGROUND = "background"


@dataclass(frozen=True)
class FilterRules:
    """Reglas inmutables para :func:`filter_candidates`."""

    min_size: tuple[int, int] = (64, 64)
    repeat_threshold: float = 0.8
    background_coverage: float = 0.85

    def __post_init__(self) -> None:
        w, h = self.min_size
        if w <= 0 or h <= 0:
            raise ValueError(f"min_size debe ser > 0, recibido: {self.min_size}")
        if not 0.0 < self.repeat_threshold <= 1.0:
            raise ValueError(
                f"repeat_threshold debe estar en (0, 1], recibido: {self.repeat_threshold}"
            )
        if not 0.0 < self.background_coverage <= 1.0:
            raise ValueError(
                f"background_coverage debe estar en (0, 1], recibido: {self.background_coverage}"
            )


@dataclass(frozen=True)
class FilterReport:
    """Resumen de una pasada de filtrado."""

    kept: tuple[ImageCandidate, ...]
    dropped: dict[FilterDecision, tuple[ImageCandidate, ...]] = field(default_factory=dict)
    total_in: int = 0

    @property
    def total_kept(self) -> int:
        return len(self.kept)

    def summary(self) -> str:
        parts = [f"{self.total_kept}/{self.total_in} figuras conservadas"]
        for decision in FilterDecision:
            if decision is FilterDecision.KEPT:
                continue
            items = self.dropped.get(decision, ())
            if items:
                parts.append(f"{len(items)} {decision.value}")
        return " · ".join(parts)


def _hash_candidate(cand: ImageCandidate) -> bytes:
    """Devuelve el SHA-256 de la imagen normalizada a RGB (post-hashable)."""
    img = cand.image
    if img.mode != "RGB":
        img = img.convert("RGB")
    return hashlib.sha256(img.tobytes()).digest()


def _is_too_small(cand: ImageCandidate, min_size: tuple[int, int]) -> bool:
    return cand.image.width < min_size[0] or cand.image.height < min_size[1]


def _is_background(
    cand: ImageCandidate,
    page_areas: Mapping[int, tuple[float, float]],
    coverage: float,
) -> bool:
    if cand.bbox is None:
        return False
    page_area = page_areas.get(cand.page)
    if page_area is None:
        return False
    page_w, page_h = page_area
    if page_w <= 0 or page_h <= 0:
        return False
    _, _, bw, bh = cand.bbox
    bbox_area = bw * bh
    page_total = page_w * page_h
    return (bbox_area / page_total) >= coverage


_DEFAULT_RULES = FilterRules()


def filter_candidates(
    candidates: Sequence[ImageCandidate],
    page_areas: Mapping[int, tuple[float, float]],
    rules: FilterRules = _DEFAULT_RULES,
) -> FilterReport:
    """Aplica los tres filtros en orden sobre ``candidates``.

    Algoritmo:

    1. Calcular hash de cada candidato.
    2. Para cada candidato, en orden:
       - Si pasa TOO_SMALL y BACKGROUND, queda en ``survivors`` (primer
         nivel) con su hash y su ``page``.
       - Si falla alguno, va al ``dropped`` con la decisión
         correspondiente.
    3. Para los ``survivors``, contar páginas distintas por hash. Si un
       hash aparece en ≥ ``rules.repeat_threshold`` de las páginas
       DISTINTAS observadas (medido sobre el total de páginas en
       ``survivors``), se conserva la primera aparición (que ya está en
       ``kept``) y el resto se mueve a ``dropped[LOGO_REPEATED]``.

    Determinista: dos corridas con el mismo input producen el mismo
    output. La primera aparición se define por el orden de la lista
    de entrada (orden de extracción).
    """
    dropped: dict[FilterDecision, list[ImageCandidate]] = {
        FilterDecision.TOO_SMALL: [],
        FilterDecision.BACKGROUND: [],
        FilterDecision.LOGO_REPEATED: [],
    }
    survivors: list[tuple[ImageCandidate, bytes]] = []

    for cand in candidates:
        if _is_too_small(cand, rules.min_size):
            dropped[FilterDecision.TOO_SMALL].append(cand)
            continue
        if _is_background(cand, page_areas, rules.background_coverage):
            dropped[FilterDecision.BACKGROUND].append(cand)
            continue
        survivors.append((cand, _hash_candidate(cand)))

    distinct_pages = {cand.page for cand, _ in survivors}
    n_pages = len(distinct_pages)
    min_required = max(1, int(n_pages * rules.repeat_threshold)) if n_pages else 0

    by_hash: dict[bytes, list[ImageCandidate]] = {}
    for cand, digest in survivors:
        by_hash.setdefault(digest, []).append(cand)

    kept: list[ImageCandidate] = []
    for _digest, items in by_hash.items():
        distinct_in_hash = {c.page for c in items}
        if min_required > 0 and len(distinct_in_hash) >= min_required:
            kept.append(items[0])
            dropped[FilterDecision.LOGO_REPEATED].extend(items[1:])
        else:
            kept.extend(items)

    return FilterReport(
        kept=tuple(kept),
        dropped={d: tuple(items) for d, items in dropped.items() if items},
        total_in=len(candidates),
    )
