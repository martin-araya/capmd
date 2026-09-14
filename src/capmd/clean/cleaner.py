"""Tipos públicos de un cleaner y helper de construcción."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from capmd.clean._stats import count_diff
from capmd.clean.context import CleanContext

__all__ = [
    "CleanResult",
    "Cleaner",
    "CleanerStat",
    "make_cleaner",
]


@dataclass(frozen=True)
class CleanResult:
    """Resultado de aplicar un cleaner a un markdown."""

    text: str
    changes: int = 0
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.changes < 0:
            raise ValueError(f"changes must be >= 0, got {self.changes}")


@dataclass(frozen=True)
class CleanerStat:
    """Métricas de un cleaner dentro de un run de :class:`Pipeline`."""

    name: str
    enabled: bool
    changes: int
    duration_ms: float
    error: str | None = None

    def __post_init__(self) -> None:
        if self.changes < 0:
            raise ValueError(f"changes must be >= 0, got {self.changes}")
        if self.duration_ms < 0:
            raise ValueError(f"duration_ms must be >= 0, got {self.duration_ms}")


@dataclass(frozen=True)
class Cleaner:
    """Cleaner configurable: nombre, enabled y callable ``apply``.

    El callable recibe el markdown y el :class:`CleanContext` y devuelve
    un :class:`CleanResult`. Usar ``make_cleaner`` para los casos simples
    ``str -> str``.
    """

    name: str
    apply: Callable[[str, CleanContext], CleanResult]
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must be non-empty")
        if self.apply is None:
            raise TypeError("apply must be a callable")

    def run(self, md: str, ctx: CleanContext) -> CleanResult:
        return self.apply(md, ctx)


def make_cleaner(name: str, fn: Callable[[str], str]) -> Cleaner:
    """Envuelve una función ``str -> str`` en un :class:`Cleaner`.

    El campo ``changes`` se calcula con :func:`capmd.clean._stats.count_diff`
    sobre el input y el output.
    """

    if not name:
        raise ValueError("name must be non-empty")
    if fn is None or not callable(fn):
        raise TypeError("fn must be a callable")

    def _apply(md: str, ctx: CleanContext) -> CleanResult:
        new_text = fn(md)
        return CleanResult(text=new_text, changes=count_diff(md, new_text))

    return Cleaner(name=name, apply=_apply)
