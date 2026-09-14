"""Tests del cleaner de de-hyphenation (D3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    DehyphenationCleaner,
    Pipeline,
    dehyphenate,
)
from capmd.models import SourceDoc


def _make_source(tmp_path: Path) -> SourceDoc:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return SourceDoc(
        path=p,
        format="pdf",
        sha256="0" * 64,
        size_bytes=p.stat().st_size,
    )


def _ctx(tmp_path: Path) -> CleanContext:
    return CleanContext(source=_make_source(tmp_path), format="pdf")


@pytest.fixture
def empty_deps() -> dict[str, object]:
    return {
        "wordlist": frozenset({"decision", "self", "control"}),
        "compounds": frozenset({"well-known", "self-contained"}),
        "spell_checker": None,
    }


def test_dehyphenate_joins_when_joined_in_dict(empty_deps: dict[str, object]) -> None:
    out = dehyphenate("deci-\nsion making", **empty_deps)
    assert out == "decision making"


def test_dehyphenate_joins_by_or_rule_when_first_in_dict(empty_deps: dict[str, object]) -> None:
    out = dehyphenate("self-\ncontrol", **empty_deps)
    assert out == "selfcontrol"


def test_dehyphenate_skips_compound_exceptions(empty_deps: dict[str, object]) -> None:
    out = dehyphenate("well-\nknown actor", **empty_deps)
    assert out == "well-\nknown actor"


def test_dehyphenate_skips_uppercase_second(empty_deps: dict[str, object]) -> None:
    out = dehyphenate("New-\nYork Times", **empty_deps)
    assert out == "New-\nYork Times"


def test_dehyphenate_skips_unknown_words(empty_deps: dict[str, object]) -> None:
    out = dehyphenate("xyzz-\nfoobar", **empty_deps)
    assert out == "xyzz-\nfoobar"


def test_dehyphenate_handles_accents() -> None:
    out = dehyphenate(
        "can-\nción",
        wordlist=frozenset(),
        compounds=frozenset(),
        spell_checker=None,
    )
    assert out == "canción"


def test_dehyphenate_is_idempotent() -> None:
    samples = [
        "deci-\nsion making",
        "well-\nknown actor",
        "New-\nYork Times",
        "hola mundo",
        "self-\ncontrol test",
        "",
    ]
    for s in samples:
        once = dehyphenate(s)
        twice = dehyphenate(once)
        assert once == twice, f"not idempotent on {s!r}"


def test_dehyphenate_empty_and_no_matches() -> None:
    assert dehyphenate("") == ""
    assert dehyphenate("hola\nmundo") == "hola\nmundo"
    assert dehyphenate("well-known") == "well-known"


def test_dehyphenate_uses_spell_checker_fallback() -> None:
    class FakeSpell:
        def __init__(self, words: set[str]) -> None:
            self.words = words

        def __contains__(self, word: str) -> bool:
            return word in self.words

    fake = FakeSpell({"decision"})
    out = dehyphenate(
        "deci-\nsion",
        wordlist=frozenset(),
        compounds=frozenset(),
        spell_checker=fake,
    )
    assert out == "decision"


def test_dehyphenate_handles_multi_match_iteratively() -> None:
    out = dehyphenate("deci-\nsion-\nmaking")
    assert "decision" in out


def test_dehyphenate_default_wordlist_english_compound() -> None:
    out = dehyphenate("well-\nknown")
    assert out == "well-\nknown"


def test_dehyphenate_default_wordlist_english_join() -> None:
    out = dehyphenate("deci-\nsion")
    assert out == "decision"


def test_dehyphenate_default_wordlist_proper_noun() -> None:
    out = dehyphenate("New-\nYork")
    assert out == "New-\nYork"


def test_dehyphenation_cleaner_default_name() -> None:
    from capmd.clean.hyphens import DEFAULT_NAME

    assert DehyphenationCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "hyphens"


def test_dehyphenation_cleaner_runs_in_pipeline(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(DehyphenationCleaner(),))
    text, stats = pipeline.run("deci-\nsion making", _ctx(tmp_path))

    assert text == "decision making"
    assert len(stats) == 1
    assert stats[0].name == "hyphens"
    assert stats[0].enabled is True
    assert stats[0].changes == 1
    assert stats[0].error is None


def test_dehyphenation_cleaner_disabled_is_skipped(tmp_path: Path) -> None:
    src = "deci-\nsion making"
    pipeline = Pipeline(cleaners=(DehyphenationCleaner(enabled=False),))

    text, stats = pipeline.run(src, _ctx(tmp_path))

    assert text == src
    assert len(stats) == 1
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_dehyphenation_cleaner_reports_count(tmp_path: Path) -> None:
    src = "deci-\nsion and pro-\ngram and well-\nknown"
    text, stats = Pipeline(cleaners=(DehyphenationCleaner(),)).run(src, _ctx(tmp_path))

    assert "decision" in text
    assert "program" in text
    assert "well-\nknown" in text
    assert stats[0].changes == 2


def test_dehyphenation_cleaner_empty_input(tmp_path: Path) -> None:
    result = DehyphenationCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_dehyphenation_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(DehyphenationCleaner(), Cleaner)


def test_dehyphenate_case_insensitive_first_match(empty_deps: dict[str, object]) -> None:
    """El wordlist es lowercase; el match puede ser uppercase. Se normaliza."""
    out = dehyphenate("Deci-\nsion", **empty_deps)
    assert out == "Decision"


@pytest.mark.parametrize(
    "compound",
    ["well-known", "self-contained", "long-term", "high-level", "real-time"],
)
def test_dehyphenate_preserves_default_compounds(compound: str) -> None:
    first, second = compound.split("-")
    src = f"{first}-\n{second}"
    out = dehyphenate(src)
    assert out == src
