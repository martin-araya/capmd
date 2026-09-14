"""Tests de wordlists y symspell singleton."""

from __future__ import annotations

from importlib.resources import files

from capmd.clean._hyphen_wordlists import (
    WORDLIST_ALL,
    WORDLIST_EN,
    WORDLIST_ES,
    get_spell_checker,
    get_wordlist,
    reset_spell_checker_cache,
    spell_checker_contains,
)


def test_wordlist_files_exist() -> None:
    base = files("capmd.clean.data")
    assert base.joinpath("words_en.txt").is_file()
    assert base.joinpath("words_es.txt").is_file()


def test_wordlist_en_minimum_size_lowercase() -> None:
    assert len(WORDLIST_EN) > 1000
    for w in WORDLIST_EN:
        assert w == w.lower()
        assert all(c.isascii() for c in w)


def test_wordlist_es_minimum_size_lowercase() -> None:
    assert len(WORDLIST_ES) > 1000
    for w in WORDLIST_ES:
        assert w == w.lower()


def test_wordlist_all_is_union() -> None:
    assert WORDLIST_ALL == WORDLIST_EN | WORDLIST_ES
    assert len(WORDLIST_ALL) >= len(WORDLIST_EN)
    assert len(WORDLIST_ALL) >= len(WORDLIST_ES)


def test_get_wordlist_returns_all() -> None:
    assert get_wordlist() == WORDLIST_ALL


def test_spell_checker_lazy_init() -> None:
    reset_spell_checker_cache()
    sc1 = get_spell_checker()
    sc2 = get_spell_checker()
    assert sc1 is sc2


def test_spell_checker_contains_known_words() -> None:
    sc = get_spell_checker()
    assert spell_checker_contains(sc, "decision")
    assert spell_checker_contains(sc, "hola")


def test_spell_checker_rejects_unknown() -> None:
    sc = get_spell_checker()
    assert not spell_checker_contains(sc, "xyzzzqqq")


def test_reset_spell_checker_cache() -> None:
    sc1 = get_spell_checker()
    reset_spell_checker_cache()
    sc2 = get_spell_checker()
    assert sc1 is not sc2
