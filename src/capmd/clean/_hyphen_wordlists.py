"""Wordlists inglés/español y singleton SymSpell.

Las listas se cargan desde ``capmd/clean/data/words_*.txt`` una sola vez
al importar el módulo. ``get_spell_checker`` es lazy para evitar coste
de inicialización si el cleaner de hyphens nunca corre.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from symspellpy import SymSpell

from capmd.clean._hyphen_compounds import COMPOUND_EXCEPTIONS

__all__ = [
    "COMPOUND_EXCEPTIONS",
    "WORDLIST_ALL",
    "WORDLIST_EN",
    "WORDLIST_ES",
    "get_spell_checker",
    "get_wordlist",
    "reset_spell_checker_cache",
    "spell_checker_contains",
]


def _load_wordlist(name: str) -> frozenset[str]:
    path = files("capmd.clean.data").joinpath(name)
    text = path.read_text(encoding="utf-8")
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip())


WORDLIST_EN: frozenset[str] = _load_wordlist("words_en.txt")
WORDLIST_ES: frozenset[str] = _load_wordlist("words_es.txt")
WORDLIST_ALL: frozenset[str] = WORDLIST_EN | WORDLIST_ES


def get_wordlist() -> frozenset[str]:
    """Devuelve el wordlist combinado (ingles + espanol)."""
    return WORDLIST_ALL


@lru_cache(maxsize=1)
def _build_spell_checker() -> SymSpell:
    sym_spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    for w in WORDLIST_ALL:
        sym_spell.create_dictionary_entry(w, 1)
    return sym_spell


def get_spell_checker() -> SymSpell:
    """Devuelve el singleton ``SymSpell`` cargado con el wordlist combinado."""
    return _build_spell_checker()


def spell_checker_contains(spell: SymSpell, word: str) -> bool:
    """Wrapper estable para verificar pertenencia exacta al diccionario."""
    return word in spell.words


def reset_spell_checker_cache() -> None:
    """Limpia el singleton. Solo para tests."""
    _build_spell_checker.cache_clear()
