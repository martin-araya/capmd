"""Orquestador de cleaners."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from capmd.clean.cleaner import Cleaner, CleanerStat
from capmd.clean.context import CleanContext

__all__ = ["Pipeline", "available_cleaner_names", "default_pipeline", "filter_pipeline"]


@dataclass(frozen=True)
class Pipeline:
    """Secuencia ordenada de :class:`Cleaner` con un modo de error.

    ``run`` aplica cada cleaner por orden sobre el markdown, propagando
    el resultado al siguiente. Los cleaners con ``enabled=False`` se
    registran en el ``CleanerStat`` pero no se invocan.

    Con ``stop_on_error=True`` (default) cualquier excepción dentro de un
    cleaner aborta el run y se propaga al caller. Con
    ``stop_on_error=False`` la excepción se captura, el cleaner registra
    ``error=<mensaje>`` y el pipeline continúa con el último texto válido.
    """

    cleaners: tuple[Cleaner, ...] = ()
    stop_on_error: bool = True

    def __post_init__(self) -> None:
        if self.cleaners is None:
            raise ValueError("cleaners must be a tuple, not None")  # pragma: no cover

    def run(self, md: str, ctx: CleanContext) -> tuple[str, list[CleanerStat]]:
        text = md
        stats: list[CleanerStat] = []
        for cleaner in self.cleaners:
            if not cleaner.enabled:
                stats.append(
                    CleanerStat(
                        name=cleaner.name,
                        enabled=False,
                        changes=0,
                        duration_ms=0.0,
                    )
                )
                continue

            start = time.perf_counter()
            try:
                result = cleaner.run(text, ctx)
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                stat = CleanerStat(
                    name=cleaner.name,
                    enabled=True,
                    changes=0,
                    duration_ms=elapsed_ms,
                    error=f"{type(exc).__name__}: {exc}",
                )
                if self.stop_on_error:
                    raise
                stats.append(stat)
                continue

            elapsed_ms = (time.perf_counter() - start) * 1000.0
            stats.append(
                CleanerStat(
                    name=cleaner.name,
                    enabled=True,
                    changes=result.changes,
                    duration_ms=elapsed_ms,
                )
            )
            text = result.text

        return text, stats


def default_pipeline() -> Pipeline:
    """Pipeline por defecto con todos los cleaners D2-D14 en orden del roadmap."""
    from capmd.clean.code_blocks import CodeBlockCleaner
    from capmd.clean.footnotes import FootnotesCleaner
    from capmd.clean.headers import HeaderFooterCleaner
    from capmd.clean.headings import HeadingReconstructor
    from capmd.clean.hyphens import DehyphenationCleaner
    from capmd.clean.kerning import KerningCleaner
    from capmd.clean.lists import ListsCleaner
    from capmd.clean.page_numbers import PageNumberCleaner
    from capmd.clean.paragraph_joins import ParagraphJoinsCleaner
    from capmd.clean.single_h1 import SingleH1Cleaner
    from capmd.clean.tables import TablesCleaner
    from capmd.clean.whitespace import WhitespaceCleaner

    return Pipeline(
        cleaners=(
            WhitespaceCleaner(),
            KerningCleaner(),
            DehyphenationCleaner(),
            HeaderFooterCleaner(),
            PageNumberCleaner(),
            HeadingReconstructor(),
            SingleH1Cleaner(),
            CodeBlockCleaner(),
            ListsCleaner(),
            TablesCleaner(),
            FootnotesCleaner(),
            ParagraphJoinsCleaner(),
        )
    )


def _validate_names(
    requested: Iterable[str],
    available: set[str],
    kind: str,
) -> None:
    unknown = set(requested) - available
    if unknown:
        raise ValueError(
            f"cleaners desconocidos ({kind}): {sorted(unknown)}. Disponibles: {sorted(available)}"
        )


def available_cleaner_names() -> tuple[str, ...]:
    """Nombres de cleaners registrados en :func:`default_pipeline`.

    Single source of truth para validar listas
    ``cleaners.enabled``/``cleaners.disabled`` del TOML
    (``capmd.config``) y de ``--only-clean``/``--skip-clean`` en CLI.
    """
    return tuple(c.name for c in default_pipeline().cleaners)


def filter_pipeline(
    base: Pipeline,
    *,
    only: tuple[str, ...] = (),
    skip: tuple[str, ...] = (),
) -> Pipeline:
    """Filtra ``base`` por nombre de cleaner.

    - ``only``: deja solo los cleaners cuyos nombres aparecen aquí.
    - ``skip``: remueve los cleaners cuyos nombres aparecen aquí.
    - Mutuamente excluyente.

    Preserva el orden original de ``base.cleaners``.
    """
    if only and skip:
        raise ValueError("only y skip son mutuamente excluyentes")
    if not only and not skip:
        return base
    available = {c.name for c in base.cleaners}
    if only:
        _validate_names(only, available, "only")
        wanted = set(only)
        return Pipeline(cleaners=tuple(c for c in base.cleaners if c.name in wanted))
    _validate_names(skip, available, "skip")
    skipped = set(skip)
    return Pipeline(cleaners=tuple(c for c in base.cleaners if c.name not in skipped))
