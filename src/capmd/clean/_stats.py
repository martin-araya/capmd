"""Heurísticas de conteo de cambios para cleaners ``str -> str``.

La regla base: ``0`` si el output es idéntico al input; en caso contrario,
una estimación basada en líneas modificadas/eliminadas. Los cleaners
concretos deben sobreescribir ``changes`` con su métrica propia cuando
dispongan de una más precisa.
"""

from __future__ import annotations

__all__ = ["count_diff"]


def count_diff(before: str, after: str) -> int:
    """Cuenta aproximada de mutaciones entre dos strings.

    Casos:
    - Vacío y vacío: ``0``.
    - Sin cambios: ``0``.
    - Solo inserciones / solo borrados en una línea: ``abs(len(after) - len(before))``.
    - Cambios multilínea: líneas distintas entre los dos sets (XOR).
    """
    if before == after:
        return 0
    if not before:
        return _measure_insertion(after)
    if not after:
        return _measure_deletion(before)

    before_lines = before.splitlines()
    after_lines = after.splitlines()

    if len(before_lines) == 1 and len(after_lines) == 1:
        return abs(len(after) - len(before))

    before_set = set(before_lines)
    after_set = set(after_lines)
    return len(before_set ^ after_set)


def _measure_insertion(text: str) -> int:
    """Cuenta inserciones cuando ``before`` era vacío."""
    if "\n" in text:
        return len(text.splitlines())
    return len(text)


def _measure_deletion(text: str) -> int:
    """Cuenta eliminaciones cuando ``after`` es vacío."""
    if "\n" in text:
        return len(text.splitlines())
    return 1
