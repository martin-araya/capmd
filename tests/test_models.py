"""Tests del dominio (A5)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from capmd.models import (
    Chapter,
    ConversionResult,
    Figure,
    PageRange,
    QualityReport,
    SourceDoc,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_source(tmp_path: Path) -> SourceDoc:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return SourceDoc(
        path=p,
        format="pdf",
        sha256="0" * 64,
        size_bytes=p.stat().st_size,
    )


def test_source_doc_rejects_negative_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="size_bytes"):
        SourceDoc(path=tmp_path / "x.pdf", format="pdf", sha256="0" * 64, size_bytes=-1)


def test_source_doc_rejects_bad_sha256(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sha256"):
        SourceDoc(path=tmp_path / "x.pdf", format="pdf", sha256="short", size_bytes=0)


def test_page_range_accepts_sorted_unique() -> None:
    pr = PageRange((1, 2, 5, 7))
    assert 5 in pr
    assert len(pr) == 4
    assert bool(pr) is True


def test_page_range_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        PageRange(())


def test_page_range_rejects_unsorted() -> None:
    with pytest.raises(ValueError, match="sorted"):
        PageRange((3, 1, 2))


def test_page_range_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="sorted"):
        PageRange((1, 2, 2))


def test_page_range_rejects_zero() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        PageRange((0, 1))


def test_page_range_rejects_bool() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        PageRange((True,))  # bool es int pero no página


def test_chapter_end_page_inclusive() -> None:
    ch = Chapter("Ownership", level=1, start_page=87, end_page=125, index=4)
    assert ch.end_page_inclusive == 124


def test_chapter_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_page"):
        Chapter("X", level=1, start_page=50, end_page=49, index=1)


def test_chapter_rejects_level_zero() -> None:
    with pytest.raises(ValueError, match="level"):
        Chapter("X", level=0, start_page=1, end_page=2, index=1)


def test_figure_rejects_zero_width(tmp_path: Path) -> None:
    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="width"):
        Figure(
            chapter_index=3,
            index=1,
            path=img,
            page=5,
            width=0,
            height=480,
        )


def test_figure_rejects_bad_bbox(tmp_path: Path) -> None:
    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="bbox"):
        Figure(
            chapter_index=3,
            index=1,
            path=img,
            page=5,
            bbox=(0.0, 0.0, 1.0),
        )


def test_quality_report_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match="word_count"):
        QualityReport(
            pages_processed=10,
            word_count=-1,
            headings_detected=2,
            figures_extracted=0,
        )


def test_quality_report_defaults() -> None:
    qr = QualityReport(
        pages_processed=10,
        word_count=1000,
        headings_detected=2,
        figures_extracted=1,
    )
    assert qr.warnings == ()
    assert qr.cleaner_stats == {}


def test_frozen_cannot_reassign() -> None:
    ch = Chapter("T", level=1, start_page=1, end_page=5, index=1)
    with pytest.raises(FrozenInstanceError):
        ch.title = "Otro"  # type: ignore[misc]


def test_hashable_and_equal() -> None:
    a = PageRange((1, 2, 3))
    b = PageRange((1, 2, 3))
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_conversion_result_round_trip(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    figure = Figure(chapter_index=1, index=1, path=img, page=3)
    report = QualityReport(
        pages_processed=5,
        word_count=200,
        headings_detected=2,
        figures_extracted=1,
    )
    res = ConversionResult(
        source=source,
        markdown="# Hi\n",
        figures=(figure,),
        report=report,
        cleaners_applied=("whitespace", "hyphens"),
        range=PageRange((3, 4, 5)),
        chapter=Chapter("Hi", level=1, start_page=3, end_page=6, index=1),
    )
    assert res.markdown == "# Hi\n"
    assert res.range is not None and 4 in res.range
    assert res.chapter is not None and res.chapter.title == "Hi"


def test_mypy_strict_passes_on_models() -> None:
    """Test literal del roadmap: mypy --strict sobre models.py pasa."""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "src/capmd/models.py"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"mypy errors:\n{result.stdout}\n{result.stderr}"
