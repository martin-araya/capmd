"""Tests del cleaner single H1 (D8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    Pipeline,
    SingleH1Cleaner,
    count_atx_level,
    enforce_single_h1,
)
from capmd.clean.single_h1 import DEFAULT_NAME
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


# --- count_atx_level ---


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("# H1", 1),
        ("## H2", 2),
        ("### H3", 3),
        ("#### H4", 4),
        ("##### H5", 5),
        ("###### H6", 6),
        ("####### Seven", 0),  # markdown no acepta >6 hashes
        ("#", 1),
        ("# ", 1),
        ("# Heading #", 1),
        ("## Heading #", 2),
        ("   # Indented", 0),  # indented: not a heading
        ("#nospace", 0),  # no space after hashes
        ("body", 0),
        ("", 0),
    ],
)
def test_count_atx_level(line: str, level: int) -> None:
    assert count_atx_level(line) == level


# --- enforce_single_h1 ---


def test_three_h1_becomes_one_h1_two_h2() -> None:
    """Literal del roadmap: 3 H1 -> 1 H1 + 2 H2."""
    src = "# A\nbody A\n# B\nbody B\n# C\nbody C"
    out = enforce_single_h1(src)
    lines = out.splitlines()
    h1_count = sum(1 for line in lines if count_atx_level(line) == 1)
    h2_count = sum(1 for line in lines if count_atx_level(line) == 2)
    assert h1_count == 1
    assert h2_count == 2
    assert lines[0] == "# A"
    assert lines[2] == "## B"
    assert lines[4] == "## C"


def test_single_h1_unchanged() -> None:
    src = "# Foo\nbody\n## Bar\nmore"
    assert enforce_single_h1(src) == src


def test_no_h1_unchanged() -> None:
    src = "## Foo\nbody"
    assert enforce_single_h1(src) == src


def test_first_h1_kept_position() -> None:
    src = "# One\nbody\n# Two\nmore\n# Three\nend"
    out = enforce_single_h1(src)
    lines = out.splitlines()
    assert lines[0] == "# One"
    assert lines[2] == "## Two"
    assert lines[4] == "## Three"


def test_h2_unchanged_when_multiple() -> None:
    src = "## A\nbody\n## B\n## C"
    assert enforce_single_h1(src) == src


def test_h6_not_demoted() -> None:
    src = "###### Six\n# H1\n###### Another Six"
    out = enforce_single_h1(src)
    assert out == src


def test_mixed_h1_h2_h3_demotes_only_h1() -> None:
    src = "# A\n## B\n### C\n# D\n## E"
    expected = "# A\n## B\n### C\n## D\n## E"
    assert enforce_single_h1(src) == expected


def test_code_fence_protects_h1_like() -> None:
    """Una línea `# not heading` dentro de un fence NO se trata como H1."""
    src = "# Real H1\n```\n# not a heading\n# another fake\n```\nbody"
    assert enforce_single_h1(src) == src


def test_tilde_fence_also_protects() -> None:
    src = "# Real H1\n~~~\n# not heading\n~~~\nbody"
    assert enforce_single_h1(src) == src


def test_closing_hashes_treated_as_h1() -> None:
    """`# Heading #` es H1; el segundo se demota."""
    src = "# First #\nbody\n# Second #\nbody"
    out = enforce_single_h1(src)
    assert "# First #" in out
    assert "## Second #" in out


def test_indented_hash_not_heading() -> None:
    """Indentación no cuenta como heading."""
    src = "   # Indented\n# Real H1\n    # Another indented"
    out = enforce_single_h1(src)
    assert out == src


def test_empty_text() -> None:
    assert enforce_single_h1("") == ""


def test_whitespace_only_text() -> None:
    """splitlines/join normaliza trailing newline; verificamos no-error."""
    src = "   \n\n   \n"
    out = enforce_single_h1(src)
    assert out.strip() == ""


def test_nested_fence_toggling() -> None:
    """Fence se cierra y se reabre correctamente."""
    src = "# H1\n```\n# fake\n```\n# H1 again?\n```\n# fake again\n```"
    out = enforce_single_h1(src)
    assert out == "# H1\n```\n# fake\n```\n## H1 again?\n```\n# fake again\n```"


def test_idempotent() -> None:
    src = "# A\nbody\n# B\nbody\n# C"
    once = enforce_single_h1(src)
    twice = enforce_single_h1(once)
    assert once == twice


# --- SingleH1Cleaner ---


def test_single_h1_cleaner_default_name() -> None:
    assert SingleH1Cleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "single_h1"


def test_single_h1_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(SingleH1Cleaner(), Cleaner)


def test_single_h1_cleaner_pipeline_integration(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(SingleH1Cleaner(),))
    text, stats = pipeline.run("# A\n# B\n# C", _ctx(tmp_path))
    assert "# A" in text
    assert "## B" in text
    assert "## C" in text
    assert len(stats) == 1
    assert stats[0].name == "single_h1"


def test_single_h1_cleaner_changes_count(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(SingleH1Cleaner(),))
    _, stats = pipeline.run("# A\n# B\n# C", _ctx(tmp_path))
    assert stats[0].changes == 2


def test_single_h1_cleaner_no_change_when_single_h1(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(SingleH1Cleaner(),))
    _, stats = pipeline.run("# Only\nbody", _ctx(tmp_path))
    assert stats[0].changes == 0


def test_single_h1_cleaner_no_change_when_no_h1(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(SingleH1Cleaner(),))
    _, stats = pipeline.run("## A\nbody", _ctx(tmp_path))
    assert stats[0].changes == 0


def test_single_h1_cleaner_disabled(tmp_path: Path) -> None:
    src = "# A\n# B\n# C"
    pipeline = Pipeline(cleaners=(SingleH1Cleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_single_h1_cleaner_empty_input(tmp_path: Path) -> None:
    result = SingleH1Cleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0
