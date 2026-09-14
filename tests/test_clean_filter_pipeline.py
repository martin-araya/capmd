"""Tests de ``default_pipeline`` y ``filter_pipeline`` (D15)."""

from __future__ import annotations

import pytest

from capmd.clean import (
    DehyphenationCleaner,
    Pipeline,
    WhitespaceCleaner,
)
from capmd.clean.context import CleanContext
from capmd.clean.pipeline import default_pipeline, filter_pipeline
from capmd.models import SourceDoc


def _make_source(tmp_path) -> SourceDoc:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return SourceDoc(
        path=p,
        format="pdf",
        sha256="0" * 64,
        size_bytes=p.stat().st_size,
    )


# --- default_pipeline ---


def test_default_pipeline_returns_pipeline() -> None:
    p = default_pipeline()
    assert isinstance(p, Pipeline)


def test_default_pipeline_has_all_cleaners() -> None:
    p = default_pipeline()
    names = {c.name for c in p.cleaners}
    expected = {
        "whitespace",
        "hyphens",
        "headers",
        "page_numbers",
        "headings",
        "single_h1",
        "code_blocks",
        "lists",
        "tables",
        "footnotes",
        "paragraph_joins",
    }
    assert names == expected


def test_default_pipeline_order_matches_roadmap() -> None:
    p = default_pipeline()
    names = [c.name for c in p.cleaners]
    assert names[0] == "whitespace"
    assert names[1] == "hyphens"
    assert names[2] == "headers"
    assert names[3] == "page_numbers"
    assert names[4] == "headings"
    assert names[5] == "single_h1"
    assert names[6] == "code_blocks"
    assert names[7] == "lists"
    assert names[8] == "tables"
    assert names[9] == "footnotes"
    assert names[10] == "paragraph_joins"


def test_default_pipeline_runs_without_error(tmp_path) -> None:
    p = default_pipeline()
    src = _make_source(tmp_path)
    ctx = CleanContext(source=src, format="pdf")
    result, stats = p.run("some input text   \n\n\nwith whitespace", ctx)
    assert isinstance(result, str)
    assert len(stats) == 11


# --- filter_pipeline ---


def test_filter_no_args_returns_base() -> None:
    p = default_pipeline()
    filtered = filter_pipeline(p)
    assert [c.name for c in filtered.cleaners] == [c.name for c in p.cleaners]


def test_filter_only_keeps_selected() -> None:
    p = default_pipeline()
    filtered = filter_pipeline(p, only=("whitespace", "hyphens"))
    assert [c.name for c in filtered.cleaners] == ["whitespace", "hyphens"]


def test_filter_skip_removes_selected() -> None:
    p = default_pipeline()
    filtered = filter_pipeline(p, skip=("tables", "footnotes"))
    names = [c.name for c in filtered.cleaners]
    assert "tables" not in names
    assert "footnotes" not in names
    assert len(names) == 9


def test_filter_preserves_order() -> None:
    p = default_pipeline()
    filtered = filter_pipeline(p, only=("footnotes", "whitespace"))
    names = [c.name for c in filtered.cleaners]
    # whitespace antes de footnotes en el original
    assert names == ["whitespace", "footnotes"]


def test_filter_only_raises_when_none_match() -> None:
    """Nombre desconocido en ``only`` produce error explícito."""
    p = Pipeline(cleaners=(WhitespaceCleaner(), DehyphenationCleaner()))
    with pytest.raises(ValueError, match="cleaners"):
        filter_pipeline(p, only=("nonexistent",))


def test_filter_raises_on_unknown_name_only() -> None:
    p = default_pipeline()
    with pytest.raises(ValueError, match="cleaners"):
        filter_pipeline(p, only=("whitespace", "bogus"))


def test_filter_raises_on_unknown_name_skip() -> None:
    p = default_pipeline()
    with pytest.raises(ValueError, match="cleaners"):
        filter_pipeline(p, skip=("bogus",))


def test_filter_raises_when_both_only_and_skip() -> None:
    p = default_pipeline()
    with pytest.raises(ValueError, match="excluyentes"):
        filter_pipeline(p, only=("whitespace",), skip=("tables",))


def test_filter_uses_cleaner_attributes() -> None:
    """filter_pipeline debe preservar la instancia del cleaner, no recrearlo."""
    p = default_pipeline()
    filtered = filter_pipeline(p, only=("whitespace",))
    assert filtered.cleaners[0] is p.cleaners[0]
