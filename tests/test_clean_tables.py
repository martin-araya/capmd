"""Tests del cleaner de tablas (D12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    Pipeline,
    TablesCleaner,
    detect_table_blocks,
    render_gfm_table,
    repair_tables,
    score_block,
    split_row,
    wrap_unstructured_table,
)
from capmd.clean.tables import (
    DEFAULT_NAME,
    DEFAULT_OPTIONS,
    GFM_SEPARATOR_RE,
    PIPE_LINE_RE,
    TableOptions,
)
from capmd.convert import Engine, insert_page_markers
from capmd.models import SourceDoc
from tests.fixtures import build


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


# --- split_row ---


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("| a | b |", ["a", "b"]),
        ("| a | b | c |", ["a", "b", "c"]),
        ("a | b |", ["a", "b"]),
        ("|  spaced  |  out  |", ["spaced", "out"]),
        ("|", [""]),
        ("||", [""]),
    ],
)
def test_split_row(line: str, expected: list[str]) -> None:
    assert split_row(line) == expected


# --- detect_table_blocks ---


def test_detect_single_block() -> None:
    lines = ["prose", "| a | b |", "| c | d |", "more prose"]
    blocks = detect_table_blocks(lines)
    assert blocks == [(1, 3)]


def test_detect_multiple_blocks() -> None:
    lines = ["| a | b |", "| c | d |", "", "| e | f |", "| g | h |"]
    blocks = detect_table_blocks(lines)
    assert blocks == [(0, 2), (3, 5)]


def test_detect_no_block_for_single_pipe_line() -> None:
    lines = ["text with | one pipe", "no pipes here"]
    assert detect_table_blocks(lines) == []


def test_detect_block_at_start_and_end() -> None:
    lines = ["| a | b |", "| c | d |", "trailing"]
    blocks = detect_table_blocks(lines)
    assert blocks == [(0, 2)]


def test_detect_block_at_end() -> None:
    lines = ["intro", "| a | b |", "| c | d |"]
    blocks = detect_table_blocks(lines)
    assert blocks == [(1, 3)]


# --- score_block ---


def test_score_full_gfm_table_is_high() -> None:
    block = [
        "| col1 | col2 | col3 |",
        "| --- | --- | --- |",
        "| a | b | c |",
        "| d | e | f |",
    ]
    assert score_block(block) >= 0.9


def test_score_aligned_rows_no_separator() -> None:
    block = ["| a | b |", "| c | d |"]
    score = score_block(block)
    assert 0.7 <= score <= 1.0


def test_score_inconsistent_widths_below_threshold() -> None:
    block = ["| a | b |", "| c |"]
    assert score_block(block) < 0.7


def test_score_only_one_row_below_threshold() -> None:
    assert score_block(["| a | b |"]) == 0.0


def test_score_single_pipe_line_zero() -> None:
    assert score_block(["a | b"]) == 0.0


def test_score_pipes_in_prose_low() -> None:
    block = ["text | with | pipes", "more | text | here"]
    assert score_block(block) < 0.7


# --- render_gfm_table ---


def test_render_gfm_table_basic() -> None:
    rows = ["| a | b |", "| c | d |"]
    out = render_gfm_table(rows)
    assert "| a | b |" in out
    assert "| c | d |" in out
    assert "| --- | --- |" in out


def test_render_gfm_table_with_header_separator() -> None:
    rows = [
        "| H1 | H2 |",
        "| --- | --- |",
        "| a | b |",
        "| c | d |",
    ]
    out = render_gfm_table(rows)
    lines = out.splitlines()
    assert lines[0] == "| H1 | H2 |"
    assert "---" in lines[1]
    assert lines[1].startswith("|")
    assert lines[1].endswith("|")
    assert lines[2].startswith("| a ")
    assert lines[3].startswith("| c ")


def test_render_gfm_table_pads_short_cells() -> None:
    rows = ["| long header | short |", "| --- | --- |", "| a | b |"]
    out = render_gfm_table(rows)
    lines = out.splitlines()
    assert "long header" in lines[0]
    assert "short" in lines[0]
    assert "long header".__len__() < lines[0].__len__()


def test_render_gfm_table_empty_cells() -> None:
    rows = ["| a |  |", "| --- | --- |", "| b | c |"]
    out = render_gfm_table(rows)
    assert "|" in out
    assert "a" in out
    assert "b" in out


def test_render_gfm_table_synthetic_separator_inserted() -> None:
    rows = ["| a | b |", "| c | d |"]
    out = render_gfm_table(rows)
    lines = out.splitlines()
    assert lines[1].startswith("|")
    assert "---" in lines[1]


def test_render_gfm_table_empty_input() -> None:
    assert render_gfm_table([]) == ""


# --- wrap_unstructured_table ---


def test_wrap_unstructured_inserts_comment() -> None:
    lines = ["a | b", "c | d"]
    out = wrap_unstructured_table(lines)
    assert "<!-- tabla no estructurada -->" in out
    assert "a | b" in out
    assert "c | d" in out


def test_wrap_unstructured_preserves_lines_order() -> None:
    lines = ["row1 | col1", "row2 | col2"]
    out = wrap_unstructured_table(lines)
    assert out.index("row1") < out.index("row2")


# --- repair_tables ---


def test_repair_gfm_table_preserves_content() -> None:
    src = "| H1 | H2 |\n| --- | --- |\n| a | b |\n| c | d |"
    out = repair_tables(src)
    assert "H1" in out
    assert "a" in out
    assert "c" in out


def test_repair_aligned_rows_adds_separator() -> None:
    src = "| a | b |\n| c | d |"
    out = repair_tables(src)
    assert "| a | b |" in out
    assert "| c | d |" in out
    assert "---" in out


def test_repair_marks_unstructured_when_inconsistent() -> None:
    src = "| a | b | c |\n| x |"
    out = repair_tables(src)
    assert "<!-- tabla no estructurada -->" in out


def test_repair_no_change_when_no_tables() -> None:
    src = "Just regular text.\nNo pipes at all."
    assert repair_tables(src) == src


def test_repair_prose_intact_when_pipes_in_text() -> None:
    src = "Some text.\n| a | b |\n| --- | --- |\n| c | d |\nMore text."
    out = repair_tables(src)
    assert "Some text." in out
    assert "More text." in out


def test_repair_table_inside_fence_preserved() -> None:
    src = "before\n```\n| not a | table |\n```\nafter"
    assert repair_tables(src) == src


def test_repair_multiple_blocks() -> None:
    src = "| a | b |\n| --- | --- |\n| c | d |\n\nProse.\n\n| e | f |\n| g | h |"
    out = repair_tables(src)
    assert "Prose." in out
    assert "| c | d |" in out or "c" in out
    assert "g" in out or "| g | h |" in out


def test_repair_empty_text() -> None:
    assert repair_tables("") == ""


def test_repair_score_threshold_options() -> None:
    src = "| a | b |\n| c | d |"
    opts_strict = TableOptions(score_threshold=0.99)
    out = repair_tables(src, options=opts_strict)
    assert "<!-- tabla no estructurada -->" in out


# --- TablesCleaner ---


def test_tables_cleaner_default_name() -> None:
    assert TablesCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "tables"


def test_tables_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(TablesCleaner(), Cleaner)


def test_tables_cleaner_pipeline_integration(tmp_path: Path) -> None:
    src = "| a | b |\n| --- | --- |\n| c | d |\n| e | f |"
    pipeline = Pipeline(cleaners=(TablesCleaner(),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert "| a | b |" in text
    assert stats[0].name == "tables"


def test_tables_cleaner_disabled(tmp_path: Path) -> None:
    src = "| a | b |\n| c | d |"
    pipeline = Pipeline(cleaners=(TablesCleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_tables_cleaner_empty_input(tmp_path: Path) -> None:
    result = TablesCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_tables_cleaner_no_change_when_no_tables(tmp_path: Path) -> None:
    src = "Prose only, no pipes."
    result = TablesCleaner().run(src, _ctx(tmp_path))
    assert result.text == src
    assert result.changes == 0


def test_tables_cleaner_changes_count(tmp_path: Path) -> None:
    src = "| a | b |\n| --- | --- |\n| c | d |"
    result = TablesCleaner().run(src, _ctx(tmp_path))
    assert result.changes >= 1


# --- End-to-end with fixture ---


def test_simple_table_3x4_roadmap(tmp_path: Path) -> None:
    """Caso literal del roadmap: tabla 3x4 -> GFM valida."""
    src = (
        "| Header A | Header B | Header C |\n"
        "| --- | --- | --- |\n"
        "| row 1 a | row 1 b | row 1 c |\n"
        "| row 2 a | row 2 b | row 2 c |\n"
        "| row 3 a | row 3 b | row 3 c |"
    )
    out = repair_tables(src)
    lines = out.splitlines()
    assert "Header A" in lines[0]
    assert "Header B" in lines[0]
    assert "Header C" in lines[0]
    assert lines[1].startswith("|")
    assert lines[1].endswith("|")
    assert "---" in lines[1]
    assert "row 1 a" in out
    assert "row 3 c" in out
    assert len(lines) == 5


def test_build_table_pdf_produces_structured_or_marked(tmp_path: Path) -> None:
    """Fixture end-to-end: el resultado debe tener tabla GFM o marker."""
    pdf = build.build_table_pdf(tmp_path / "table.pdf")
    pages = Engine().convert_pages(pdf)
    md = insert_page_markers(pages)
    out = TablesCleaner().run(md, _ctx(tmp_path)).text
    assert "|" in out or "<!-- tabla no estructurada -->" in out


# --- constants sanity ---


def test_pipe_line_re_matches() -> None:
    assert PIPE_LINE_RE.match("| a | b |")
    assert PIPE_LINE_RE.match("| a | b | c |")
    assert not PIPE_LINE_RE.match("text only")
    assert not PIPE_LINE_RE.match("a | single")
    assert not PIPE_LINE_RE.match("a | b")


def test_gfm_separator_re_matches() -> None:
    assert GFM_SEPARATOR_RE.match("| --- | --- |")
    assert GFM_SEPARATOR_RE.match("| :--- | :---: | ---: |")
    assert not GFM_SEPARATOR_RE.match("| a | b |")


def test_default_options_is_table_options() -> None:
    assert isinstance(DEFAULT_OPTIONS, TableOptions)
