"""Tests del cleaner de listas (D11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    ListsCleaner,
    Pipeline,
    repair_bullets,
    repair_lists,
    repair_numbered_lists,
)
from capmd.clean.lists import (
    BROKEN_BULLETS_MAP,
    DEFAULT_NAME,
    NUMBERED_ITEM_RE,
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


# --- repair_bullets ---


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("• x", "- x"),
        ("‣ y", "- y"),
        ("– z", "- z"),
        ("◦ a", "- a"),
        ("▪ b", "- b"),
        ("· c", "- c"),
        ("* x", "* x"),
        ("- x", "- x"),
        ("+ x", "+ x"),
    ],
)
def test_repair_bullets_basic(src: str, expected: str) -> None:
    assert repair_bullets(src) == expected


def test_repair_bullets_indented() -> None:
    assert repair_bullets("    • item") == "    - item"
    assert repair_bullets("  ‣ item") == "  - item"


def test_repair_bullets_only_at_line_start() -> None:
    assert repair_bullets("text • in middle") == "text • in middle"


def test_repair_bullets_only_with_whitespace_after() -> None:
    """Sin espacio después del char, no se trata como bullet."""
    assert repair_bullets("•item") == "•item"
    assert repair_bullets("•text") == "•text"


def test_repair_bullets_multiline() -> None:
    src = "• first\n‣ second\n– third\nregular text"
    out = repair_bullets(src)
    assert "- first" in out
    assert "- second" in out
    assert "- third" in out
    assert "regular text" in out


def test_repair_bullets_empty_text() -> None:
    assert repair_bullets("") == ""


def test_repair_bullets_no_changes_when_no_broken_bullets() -> None:
    src = "Just some text.\nWith * and - chars but not at line starts."
    assert repair_bullets(src) == src


def test_repair_bullets_preserves_inline_bullets() -> None:
    """Un bullet char en medio de una línea NO se reemplaza."""
    assert repair_bullets("prices • 5€") == "prices • 5€"


# --- repair_numbered_lists ---


def test_two_items_with_blank_merge() -> None:
    src = "1. First\n\n2. Second"
    assert repair_numbered_lists(src) == "1. First\n2. Second"


def test_five_items_with_blanks_roadmap() -> None:
    """Literal del roadmap: 5 items con blancos → 5 items consecutivos."""
    src = "1. Uno\n\n2. Dos\n\n3. Tres\n\n4. Cuatro\n\n5. Cinco"
    expected = "1. Uno\n2. Dos\n3. Tres\n4. Cuatro\n5. Cinco"
    assert repair_numbered_lists(src) == expected


def test_already_adjacent_items_unchanged() -> None:
    src = "1. First\n2. Second\n3. Third"
    assert repair_numbered_lists(src) == src


def test_single_item_unchanged() -> None:
    src = "intro\n\n1. Only item\n\noutro"
    assert repair_numbered_lists(src) == src


def test_prose_between_items_does_not_merge() -> None:
    """Items separados por prosa NO se mergean."""
    src = "1. First\n\nOther prose here.\n\n2. Second"
    assert repair_numbered_lists(src) == src


def test_indented_continuation_breaks_block() -> None:
    """Una continuación indentada (no numbered) rompe el bloque."""
    src = "1. First\n   continuation\n\n2. Second"
    out = repair_numbered_lists(src)
    assert "1. First\n   continuation" in out
    assert "2. Second" in out


def test_block_at_start_of_document() -> None:
    src = "1. Uno\n\n2. Dos\n\n3. Tres"
    expected = "1. Uno\n2. Dos\n3. Tres"
    assert repair_numbered_lists(src) == expected


def test_block_at_end_of_document() -> None:
    src = "intro\n\n1. Last\n\n2. Block"
    expected = "intro\n\n1. Last\n2. Block"
    assert repair_numbered_lists(src) == expected


def test_multiple_blank_lines_between_items() -> None:
    src = "1. A\n\n\n\n2. B"
    assert repair_numbered_lists(src) == "1. A\n2. B"


def test_numbered_with_paren_style() -> None:
    """Markdown acepta ``1) foo`` como lista ordenada."""
    src = "1) First\n\n2) Second"
    assert repair_numbered_lists(src) == "1) First\n2) Second"


def test_indented_numbered_items() -> None:
    """Items con indentación se mergean igual."""
    src = "    1. First\n\n    2. Second"
    assert repair_numbered_lists(src) == "    1. First\n    2. Second"


def test_repair_empty_text() -> None:
    assert repair_numbered_lists("") == ""


def test_repair_no_changes_when_no_numbered() -> None:
    src = "Just regular text.\n\nMore text."
    assert repair_numbered_lists(src) == src


def test_block_followed_by_prose() -> None:
    src = "1. A\n\n2. B\n\nProse after.\n\n3. C\n\n4. D"
    expected = "1. A\n2. B\n\nProse after.\n\n3. C\n4. D"
    assert repair_numbered_lists(src) == expected


# --- repair_lists (combinado) ---


def test_combined_bullets_and_numbers() -> None:
    src = "• first bullet\n\n• second bullet\n\n1. numbered one\n\n2. numbered two"
    out = repair_lists(src)
    assert "- first bullet" in out
    assert "- second bullet" in out
    assert "1. numbered one" in out
    assert "2. numbered two" in out


def test_combined_no_changes() -> None:
    src = "1. First\n2. Second\n\n* item A\n- item B"
    assert repair_lists(src) == src


# --- fences ---


def test_bullet_inside_fence_preserved() -> None:
    src = "before\n```\n• item inside\n```\nafter"
    assert repair_bullets(src) == src


def test_numbered_inside_fence_not_merged() -> None:
    src = "before\n```\n1. foo\n\n2. bar\n```\nafter"
    assert repair_numbered_lists(src) == src


def test_bullet_outside_and_inside_fence() -> None:
    src = "• outside\n```\n• inside\n```\n• outside2"
    out = repair_bullets(src)
    assert "- outside" in out
    assert "- outside2" in out
    assert "• inside" in out  # inside preserved


# --- ListsCleaner ---


def test_lists_cleaner_default_name() -> None:
    assert ListsCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "lists"


def test_lists_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(ListsCleaner(), Cleaner)


def test_lists_cleaner_pipeline_integration(tmp_path: Path) -> None:
    src = "1. A\n\n2. B\n\n3. C"
    pipeline = Pipeline(cleaners=(ListsCleaner(),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == "1. A\n2. B\n3. C"
    assert stats[0].name == "lists"
    assert stats[0].changes >= 1


def test_lists_cleaner_reports_changes(tmp_path: Path) -> None:
    src = "• a\n\n1. b\n\n2. c"
    result = ListsCleaner().run(src, _ctx(tmp_path))
    assert result.changes >= 2


def test_lists_cleaner_disabled(tmp_path: Path) -> None:
    src = "• a\n\n1. b\n\n2. c"
    pipeline = Pipeline(cleaners=(ListsCleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_lists_cleaner_empty_input(tmp_path: Path) -> None:
    result = ListsCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_lists_cleaner_no_change_when_well_formed(tmp_path: Path) -> None:
    src = "1. A\n2. B\n- x\n- y"
    result = ListsCleaner().run(src, _ctx(tmp_path))
    assert result.text == src
    assert result.changes == 0


def test_lists_cleaner_5_items_fixture_roadmap(tmp_path: Path) -> None:
    """Caso literal del roadmap."""
    src = "1. Item uno\n\n2. Item dos\n\n3. Item tres\n\n4. Item cuatro\n\n5. Item cinco"
    result = ListsCleaner().run(src, _ctx(tmp_path))
    assert result.text == "1. Item uno\n2. Item dos\n3. Item tres\n4. Item cuatro\n5. Item cinco"
    assert result.changes >= 1


# --- constants sanity ---


def test_broken_bullets_map_size() -> None:
    assert len(BROKEN_BULLETS_MAP) == 6


def test_numbered_item_re_matches_typical() -> None:
    assert NUMBERED_ITEM_RE.match("1. foo")
    assert NUMBERED_ITEM_RE.match("1) foo")
    assert NUMBERED_ITEM_RE.match("42. bar")
    assert not NUMBERED_ITEM_RE.match("foo")
    assert not NUMBERED_ITEM_RE.match("Total: 100.")
