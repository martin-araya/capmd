"""Cleaner identidad: devuelve el markdown sin tocar.

Útil como placeholder en pipelines, en tests y como destino del flag
``--no-clean`` (D15).
"""

from __future__ import annotations

from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = ["NoOpCleaner"]


class NoOpCleaner(Cleaner):
    """Cleaner que no modifica nada."""

    def __init__(self, name: str = "noop") -> None:
        super().__init__(name=name, enabled=True, apply=self._apply)

    @staticmethod
    def _apply(md: str, ctx: CleanContext) -> CleanResult:
        return CleanResult(text=md, changes=0)
