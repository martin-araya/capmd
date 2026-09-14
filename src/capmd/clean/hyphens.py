"""De-hyphenation: une ``pala-\\nbra`` preservando compuestos legítimos.

Algoritmo por match ``first-\\nsecond``:

1. Si ``second`` empieza en mayúscula → skip (proper noun).
2. Si ``first-second`` está en ``COMPOUND_EXCEPTIONS`` → skip.
3. Si ``firstsecond`` está en el wordlist → join.
4. Si no, fallback via ``symspell`` → join.
5. Si ``second`` empieza en minúscula y ``first`` está en el wordlist → join
   (roadmap OR rule, con salvaguarda de que ``first`` sea palabra conocida).

Triple hyphenation (``cost-\\nof-\\nliving``): tras cada join el texto
cambia y se re-escanea desde el inicio.
"""

from __future__ import annotations

import re

from capmd.clean._hyphen_compounds import COMPOUND_EXCEPTIONS
from capmd.clean._hyphen_wordlists import (
    get_spell_checker,
    get_wordlist,
    spell_checker_contains,
)
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "DEFAULT_NAME",
    "DehyphenationCleaner",
    "dehyphenate",
]

DEFAULT_NAME = "hyphens"

HYPHEN_BREAK_RE = re.compile(
    r"([^\W\d_]+)-\n([^\W\d_]+)",
    flags=re.UNICODE,
)


def _should_join(
    first: str,
    second: str,
    wordlist: frozenset[str],
    compounds: frozenset[str],
    spell: object,
) -> bool:
    if not second or not second[0].islower():
        return False
    if f"{first}-{second}" in compounds:
        return False
    joined_lower = (first + second).lower()
    if joined_lower in wordlist:
        return True
    if spell is not None and spell_checker_contains(spell, joined_lower):
        return True
    return first.lower() in wordlist


def _dehyphenate_with_count(
    text: str,
    *,
    wordlist: frozenset[str],
    compounds: frozenset[str],
    spell: object,
) -> tuple[str, int]:
    """Núcleo: devuelve ``(texto_procesado, n_joins)``."""
    if not text:
        return text, 0

    out = text
    n_joined = 0
    last_end = 0

    while True:
        match = HYPHEN_BREAK_RE.search(out, last_end)
        if match is None:
            break
        first, second = match.group(1), match.group(2)
        if _should_join(first, second, wordlist, compounds, spell):
            out = out[: match.end(1)] + second + out[match.end() :]
            n_joined += 1
            last_end = match.end(1) + len(second)
        else:
            last_end = match.end()

    return out, n_joined


def dehyphenate(
    text: str,
    *,
    wordlist: frozenset[str] | None = None,
    compounds: frozenset[str] | None = None,
    spell_checker: object | None = None,
) -> str:
    """Une hyphen-line-break pairs en ``text``.

    Todas las dependencias son inyectables para tests; los defaults se
    cargan perezosamente desde ``_hyphen_wordlists``.
    """
    wl = wordlist if wordlist is not None else get_wordlist()
    cps = compounds if compounds is not None else COMPOUND_EXCEPTIONS
    sc = spell_checker if spell_checker is not None else get_spell_checker()
    out, _ = _dehyphenate_with_count(text, wordlist=wl, compounds=cps, spell=sc)
    return out


class DehyphenationCleaner(Cleaner):
    """Cleaner que une ``pala-\\nbra`` → ``palabra`` preservando compuestos."""

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    @staticmethod
    def _apply(md: str, ctx: CleanContext) -> CleanResult:
        from capmd.clean._fences import split_outside_fences

        segments = split_outside_fences(md)
        out_parts: list[str] = []
        n_joined = 0
        for seg, in_fence in segments:
            if in_fence:
                out_parts.append(seg)
                continue
            new_text, n = _dehyphenate_with_count(
                seg,
                wordlist=get_wordlist(),
                compounds=COMPOUND_EXCEPTIONS,
                spell=get_spell_checker(),
            )
            out_parts.append(new_text)
            n_joined += n
        return CleanResult(text="".join(out_parts), changes=n_joined)
