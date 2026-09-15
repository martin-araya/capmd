"""Tests unitarios de ``capmd.report`` (F6)."""

from __future__ import annotations

import json

import pytest

from capmd.report import (
    REPORT_SCHEMA_VERSION,
    CleanerCounts,
    HeadingCounts,
    ReportOutput,
    ReportStats,
    collect_stats,
    collect_warnings,
    render_json,
    render_text,
)

# --- HeadingCounts ---------------------------------------------------------


def test_heading_counts_empty() -> None:
    hc = HeadingCounts.from_markdown("")
    assert hc.total == 0
    assert (hc.h1, hc.h2, hc.h3, hc.h4, hc.h5, hc.h6) == (0, 0, 0, 0, 0, 0)


def test_heading_counts_each_level() -> None:
    md = (
        "# h1a\n"
        "## h2a\n"
        "## h2b\n"
        "### h3a\n"
        "#### h4a\n"
        "##### h5a\n"
        "###### h6a\n"
    )
    hc = HeadingCounts.from_markdown(md)
    assert hc.h1 == 1
    assert hc.h2 == 2
    assert hc.h3 == 1
    assert hc.h4 == 1
    assert hc.h5 == 1
    assert hc.h6 == 1
    assert hc.total == 7


def test_heading_uniform_h2() -> None:
    hc = HeadingCounts(h2=3)
    assert hc.has_uniform_h2_or_h3()
    assert hc.has_uniform_h2_or_h3() is True


def test_heading_uniform_h3() -> None:
    hc = HeadingCounts(h3=5)
    assert hc.has_uniform_h2_or_h3() is True


def test_heading_not_uniform_when_mixed() -> None:
    hc = HeadingCounts(h1=1, h2=3)
    assert not hc.has_uniform_h2_or_h3()


def test_heading_uniform_requires_two_or_more() -> None:
    hc = HeadingCounts(h2=1)
    assert not hc.has_uniform_h2_or_h3()


# --- CleanerCounts --------------------------------------------------------


def test_cleaner_counts_empty() -> None:
    cc = CleanerCounts()
    assert cc.total_changes == 0
    assert cc.per_cleaner == {}


def test_cleaner_counts_aggregates_same_cleaner() -> None:
    cc = CleanerCounts.from_stats(
        (
            {"name": "whitespace", "changes": 2},
            {"name": "whitespace", "changes": 3},
            {"name": "headers", "changes": 1},
        )
    )
    assert cc.per_cleaner == {"whitespace": 5, "headers": 1}
    assert cc.total_changes == 6


# --- collect_stats ---------------------------------------------------------


def test_collect_stats_basic() -> None:
    stats = collect_stats(
        raw_markdown="# Title\n\nBody content here.\n\n## A\nbody a\n",
        final_markdown="# Title\n\nBody content here.\n\n## A\nbody a\n",
        pages=1,
        figures_count=2,
        cleaner_stats=({"name": "whitespace", "changes": 5},),
        elapsed_seconds=0.5,
        source_format="pdf",
    )
    assert stats.pages == 1
    assert stats.figures == 2
    assert stats.words > 0
    assert stats.headings.h1 == 1
    assert stats.headings.h2 == 1
    assert stats.headings.total == 2
    assert stats.cleaners.per_cleaner == {"whitespace": 5}
    assert stats.cleaners.total_changes == 5
    assert stats.deletion_ratio == 0.0
    assert stats.elapsed_seconds == 0.5
    assert stats.source_format == "pdf"


def test_collect_stats_empty_output() -> None:
    stats = collect_stats(
        raw_markdown="",
        final_markdown="",
        pages=3,
        figures_count=0,
        cleaner_stats=(),
        elapsed_seconds=0.1,
        source_format="pdf",
    )
    assert stats.words == 0
    assert stats.figures == 0
    assert stats.deletion_ratio == 0.0


def test_collect_stats_deletion_ratio() -> None:
    """raw=10 chars, cleaned=4 chars → 60% borrado."""
    stats = collect_stats(
        raw_markdown="x" * 10,
        final_markdown="xx",
        pages=1,
        figures_count=0,
        cleaner_stats=(),
        elapsed_seconds=0.0,
        source_format="pdf",
    )
    assert stats.deletion_ratio == pytest.approx(0.8, abs=0.01)


# --- collect_warnings ------------------------------------------------------


def test_no_warnings_when_normal() -> None:
    stats = ReportStats(
        pages=5,
        words=1000,
        headings=HeadingCounts(h1=1, h2=5),
        figures=3,
        cleaners=CleanerCounts(total_changes=10),
        raw_chars=2000,
        cleaned_chars=1900,
        deletion_ratio=0.05,
        elapsed_seconds=0.3,
        source_format="pdf",
    )
    warnings = collect_warnings(stats, no_clean=False, format="pdf")
    assert warnings == []


def test_warning_empty_output() -> None:
    stats = ReportStats(
        pages=3,
        words=0,
        headings=HeadingCounts(),
        figures=0,
        cleaners=CleanerCounts(total_changes=0),
        raw_chars=0,
        cleaned_chars=0,
        deletion_ratio=0.0,
        elapsed_seconds=0.1,
        source_format="pdf",
    )
    warnings = collect_warnings(stats, no_clean=False, format="pdf")
    codes = {w["code"] for w in warnings}
    assert "empty_output" in codes
    assert "no_headings" in codes
    assert "scanned_pdf" in codes


def test_warning_scanned_pdf_only() -> None:
    """No 'empty_output' (hay palabras) pero sí 'scanned_pdf' (pocas)."""
    stats = ReportStats(
        pages=5,
        words=20,  # 4 palabras/página → < 10 → scanned_pdf
        headings=HeadingCounts(h2=2),
        figures=0,
        cleaners=CleanerCounts(total_changes=5),
        raw_chars=200,
        cleaned_chars=180,
        deletion_ratio=0.10,
        elapsed_seconds=0.2,
        source_format="pdf",
    )
    warnings = collect_warnings(stats, no_clean=False, format="pdf")
    codes = {w["code"] for w in warnings}
    assert "scanned_pdf" in codes
    assert "empty_output" not in codes


def test_warning_no_figures_large_pdf() -> None:
    stats = ReportStats(
        pages=10,
        words=2000,
        headings=HeadingCounts(h1=1, h2=8),
        figures=0,
        cleaners=CleanerCounts(total_changes=20),
        raw_chars=4000,
        cleaned_chars=3900,
        deletion_ratio=0.025,
        elapsed_seconds=0.5,
        source_format="pdf",
    )
    warnings = collect_warnings(stats, no_clean=False, format="pdf")
    codes = {w["code"] for w in warnings}
    assert "no_figures" in codes
    assert "empty_output" not in codes


def test_warning_over_cleanup_skipped_with_no_clean() -> None:
    stats = ReportStats(
        pages=1,
        words=10,
        headings=HeadingCounts(h1=1),
        figures=0,
        cleaners=CleanerCounts(total_changes=100),
        raw_chars=1000,
        cleaned_chars=400,
        deletion_ratio=0.6,
        elapsed_seconds=0.1,
        source_format="pdf",
    )
    # Con --no-clean NO se emite over_cleanup.
    warnings = collect_warnings(stats, no_clean=True, format="pdf")
    codes = {w["code"] for w in warnings}
    assert "over_cleanup" not in codes


def test_warning_over_cleanup_when_cleaning() -> None:
    stats = ReportStats(
        pages=1,
        words=10,
        headings=HeadingCounts(h1=1),
        figures=0,
        cleaners=CleanerCounts(total_changes=100),
        raw_chars=1000,
        cleaned_chars=400,
        deletion_ratio=0.6,
        elapsed_seconds=0.1,
        source_format="pdf",
    )
    warnings = collect_warnings(stats, no_clean=False, format="pdf")
    codes = {w["code"] for w in warnings}
    assert "over_cleanup" in codes


def test_warning_uniform_headings() -> None:
    stats = ReportStats(
        pages=5,
        words=1000,
        headings=HeadingCounts(h2=10),
        figures=3,
        cleaners=CleanerCounts(total_changes=10),
        raw_chars=2000,
        cleaned_chars=1900,
        deletion_ratio=0.05,
        elapsed_seconds=0.3,
        source_format="pdf",
    )
    warnings = collect_warnings(stats, no_clean=False, format="pdf")
    codes = {w["code"] for w in warnings}
    assert "uniform_headings" in codes


def test_warning_no_headings_only_on_multipage_pdf() -> None:
    """Una sola página de PDF sin headings NO dispara 'no_headings'."""
    stats = ReportStats(
        pages=1,
        words=10,
        headings=HeadingCounts(),
        figures=0,
        cleaners=CleanerCounts(),
        raw_chars=20,
        cleaned_chars=20,
        deletion_ratio=0.0,
        elapsed_seconds=0.1,
        source_format="pdf",
    )
    warnings = collect_warnings(stats, no_clean=False, format="pdf")
    codes = {w["code"] for w in warnings}
    assert "no_headings" not in codes  # pages < NO_HEADINGS_MIN_PAGES


def test_warning_format_must_be_pdf() -> None:
    """Los warnings PDF-specific solo disparan con format='pdf'."""
    stats = ReportStats(
        pages=5,
        words=10,  # scanned ratio
        headings=HeadingCounts(),
        figures=0,
        cleaners=CleanerCounts(),
        raw_chars=200,
        cleaned_chars=180,
        deletion_ratio=0.10,
        elapsed_seconds=0.2,
        source_format="epub",
    )
    warnings = collect_warnings(stats, no_clean=False, format="epub")
    codes = {w["code"] for w in warnings}
    # scanned_pdf / no_headings / no_figures son PDF-specific.
    assert "scanned_pdf" not in codes
    assert "no_headings" not in codes
    assert "no_figures" not in codes


# --- render_json / render_text ---------------------------------------------


def _make_output(*, warnings=(), fmt="json") -> ReportOutput:
    return ReportOutput(
        schema_version=REPORT_SCHEMA_VERSION,
        stats=ReportStats(
            pages=3,
            words=100,
            headings=HeadingCounts(h1=1, h2=2),
            figures=1,
            cleaners=CleanerCounts(per_cleaner={"whitespace": 5}, total_changes=5),
            raw_chars=200,
            cleaned_chars=180,
            deletion_ratio=0.10,
            elapsed_seconds=0.5,
            source_format="pdf",
        ),
        warnings=warnings,
        format=fmt,
    )


def test_render_json_parses():
    out = _make_output(
        warnings=({"code": "x", "message": "y", "suggestion": "z"},)
    )
    text = render_json(out)
    parsed = json.loads(text)
    assert parsed["report_schema_version"] == REPORT_SCHEMA_VERSION
    assert parsed["stats"]["words"] == 100
    assert parsed["stats"]["source_format"] == "pdf"
    assert parsed["warnings"] == [{"code": "x", "message": "y", "suggestion": "z"}]


def test_render_text_contains_key_stats():
    out = _make_output()
    text = render_text(out)
    # Estructura human-readable; no asumimos un header exacto, pero las
    # stats clave deben aparecer.
    assert "100" in text  # words
    assert "whitespace" in text  # cleaner name
    assert "pdf" in text  # source_format


def test_render_text_shows_warnings():
    out = _make_output(
        warnings=({"code": "scanned_pdf", "message": "PDF parece escaneado",
                  "suggestion": "ejecutá OCR"},),
    )
    text = render_text(out)
    assert "scanned_pdf" in text or "escaneado" in text
