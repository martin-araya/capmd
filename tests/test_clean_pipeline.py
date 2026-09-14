"""Tests del andamiaje :class:`Pipeline` (D1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    Cleaner,
    CleanerStat,
    CleanResult,
    Pipeline,
    make_cleaner,
)
from capmd.models import PageRange, SourceDoc


def _make_source(tmp_path: Path) -> SourceDoc:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return SourceDoc(
        path=p,
        format="pdf",
        sha256="0" * 64,
        size_bytes=p.stat().st_size,
    )


def _ctx(tmp_path: Path, page_range: PageRange | None = None) -> CleanContext:
    return CleanContext(source=_make_source(tmp_path), format="pdf", page_range=page_range)


def test_empty_pipeline_returns_input_intact(tmp_path: Path) -> None:
    md = "hola\nmundo\n"
    out, stats = Pipeline().run(md, _ctx(tmp_path))
    assert out == md
    assert stats == []


def test_empty_pipeline_empty_input(tmp_path: Path) -> None:
    out, stats = Pipeline().run("", _ctx(tmp_path))
    assert out == ""
    assert stats == []


def test_two_cleaners_apply_in_order(tmp_path: Path) -> None:
    prepend = make_cleaner("prepend", lambda s: f"A:{s}")
    append = make_cleaner("append", lambda s: f"{s}:Z")
    pipeline = Pipeline((prepend, append))

    out, stats = pipeline.run("input", _ctx(tmp_path))

    assert out == "A:input:Z"
    assert [s.name for s in stats] == ["prepend", "append"]
    assert all(s.enabled for s in stats)


def test_disabled_cleaner_is_skipped_and_recorded(tmp_path: Path) -> None:
    prepend = make_cleaner("prepend", lambda s: f"A:{s}")
    skipped = make_cleaner("skipped", lambda s: f"X:{s}")
    object.__setattr__(skipped, "enabled", False)
    append = make_cleaner("append", lambda s: f"{s}:Z")
    pipeline = Pipeline((prepend, skipped, append))

    out, stats = pipeline.run("in", _ctx(tmp_path))

    assert out == "A:in:Z"
    assert [s.name for s in stats] == ["prepend", "skipped", "append"]
    assert stats[0].enabled is True
    assert stats[1].enabled is False
    assert stats[1].changes == 0
    assert stats[1].duration_ms == 0.0
    assert stats[2].enabled is True


def test_cleaner_counting_reports_changes(tmp_path: Path) -> None:
    def drop_two(md: str, ctx: CleanContext) -> CleanResult:
        lines = md.splitlines(keepends=True)
        return CleanResult(text="".join(lines[:1]), changes=2)

    cleaner = Cleaner(name="drop_two", apply=drop_two)
    out, stats = Pipeline((cleaner,)).run("a\nb\nc\n", _ctx(tmp_path))

    assert out == "a\n"
    assert len(stats) == 1
    assert stats[0].changes == 2
    assert stats[0].duration_ms >= 0.0


def test_cleaner_propagates_context(tmp_path: Path) -> None:
    def echo_format(md: str, ctx: CleanContext) -> CleanResult:
        return CleanResult(text=f"{md}[{ctx.format}]", changes=1)

    cleaner = Cleaner(name="echo", apply=echo_format)
    out, stats = Pipeline((cleaner,)).run("x", _ctx(tmp_path))

    assert out == "x[pdf]"
    assert stats[0].changes == 1


def test_error_propagates_when_stop_on_error_true(tmp_path: Path) -> None:
    def boom(md: str, ctx: CleanContext) -> CleanResult:
        raise RuntimeError("explota")

    cleaner = Cleaner(name="boom", apply=boom)
    pipeline = Pipeline((cleaner,), stop_on_error=True)

    with pytest.raises(RuntimeError, match="explota"):
        pipeline.run("in", _ctx(tmp_path))


def test_error_collected_when_stop_on_error_false(tmp_path: Path) -> None:
    def boom(md: str, ctx: CleanContext) -> CleanResult:
        raise RuntimeError("explota")

    def append(md: str, ctx: CleanContext) -> CleanResult:
        return CleanResult(text=f"{md}!", changes=1)

    pipeline = Pipeline(
        (Cleaner(name="boom", apply=boom), make_cleaner("append", lambda s: f"{s}!")),
        stop_on_error=False,
    )

    out, stats = pipeline.run("in", _ctx(tmp_path))

    assert out == "in!"
    assert len(stats) == 2
    assert stats[0].name == "boom"
    assert stats[0].error is not None
    assert "RuntimeError" in stats[0].error
    assert "explota" in stats[0].error
    assert stats[1].name == "append"
    assert stats[1].error is None
    assert stats[1].changes == 1


def test_make_cleaner_helper_counts_diff(tmp_path: Path) -> None:
    upper = make_cleaner("upper", str.upper)
    drop_last = make_cleaner("drop_last", lambda s: "\n".join(s.splitlines()[:-1]))

    _, stats_upper = Pipeline((upper,)).run("abc\n", _ctx(tmp_path))
    assert stats_upper[0].changes == 0

    _, stats_drop = Pipeline((drop_last,)).run("abc\nxyz\n", _ctx(tmp_path))
    assert stats_drop[0].changes >= 1


def test_stats_preserve_order_with_disabled_and_errors(tmp_path: Path) -> None:
    def boom(md: str, ctx: CleanContext) -> CleanResult:
        raise ValueError("x")

    a = make_cleaner("a", lambda s: s)
    b = Cleaner(name="boom", apply=boom)
    object.__setattr__(b, "enabled", False)
    c = make_cleaner("c", lambda s: s)
    pipeline = Pipeline((a, b, c), stop_on_error=False)

    _, stats = pipeline.run("in", _ctx(tmp_path))
    assert [s.name for s in stats] == ["a", "boom", "c"]
    assert stats[0].error is None
    assert stats[1].enabled is False
    assert stats[1].error is None
    assert stats[2].error is None


def test_pipeline_with_cleancontext_carries_page_range(tmp_path: Path) -> None:
    rng = PageRange(pages=(1, 2, 3))

    def consume(md: str, ctx: CleanContext) -> CleanResult:
        assert ctx.page_range is rng
        assert ctx.profile == "study"
        return CleanResult(text=md, changes=0)

    cleaner = Cleaner(name="consume", apply=consume)
    ctx = CleanContext(
        source=_make_source(tmp_path),
        format="pdf",
        page_range=rng,
        profile="study",
    )
    Pipeline((cleaner,)).run("x", ctx)


def test_cleaner_stat_validates_non_negative_changes() -> None:
    with pytest.raises(ValueError):
        CleanerStat(name="x", enabled=True, changes=-1, duration_ms=0.0)
    with pytest.raises(ValueError):
        CleanerStat(name="x", enabled=True, changes=0, duration_ms=-0.1)
