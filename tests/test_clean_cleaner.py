"""Tests de :class:`Cleaner`, :func:`make_cleaner` y :class:`CleanResult`."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import CleanContext, Cleaner, CleanResult, make_cleaner
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


def test_clean_result_default_changes_is_zero() -> None:
    r = CleanResult(text="hola")
    assert r.text == "hola"
    assert r.changes == 0
    assert r.notes == ()


def test_clean_result_rejects_negative_changes() -> None:
    with pytest.raises(ValueError):
        CleanResult(text="x", changes=-1)


def test_cleaner_requires_name_and_callable(tmp_path: Path) -> None:
    def fn(md: str, ctx: CleanContext) -> CleanResult:
        return CleanResult(text=md)

    with pytest.raises(ValueError):
        Cleaner(name="", apply=fn)
    with pytest.raises(TypeError):
        Cleaner(name="x", apply=None)  # type: ignore[arg-type]


def test_cleaner_run_invokes_apply(tmp_path: Path) -> None:
    called: list[str] = []

    def fn(md: str, ctx: CleanContext) -> CleanResult:
        called.append(md)
        return CleanResult(text=md.upper(), changes=1)

    cleaner = Cleaner(name="up", apply=fn)
    out = cleaner.run("hi", _ctx(tmp_path))

    assert out.text == "HI"
    assert out.changes == 1
    assert called == ["hi"]


def test_make_cleaner_wraps_str_callable() -> None:
    cleaner = make_cleaner("strip", str.strip)

    ctx = CleanContext(source=_make_source(Path("/tmp")), format="pdf")
    res = cleaner.run("  hola  ", ctx)

    assert res.text == "hola"
    assert res.changes >= 0


def test_make_cleaner_validates_name_and_callable() -> None:
    with pytest.raises(ValueError):
        make_cleaner("", str.upper)
    with pytest.raises(TypeError):
        make_cleaner("x", None)  # type: ignore[arg-type]


def test_make_cleaner_reports_no_changes_when_unchanged(tmp_path: Path) -> None:
    cleaner = make_cleaner("id", lambda s: s)
    res = cleaner.run("igual\n", _ctx(tmp_path))
    assert res.changes == 0
