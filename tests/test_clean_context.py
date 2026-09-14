"""Tests de :class:`CleanContext`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from capmd.clean import CleanContext
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


def test_context_minimal(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    ctx = CleanContext(source=src, format="pdf")

    assert ctx.source is src
    assert ctx.format == "pdf"
    assert ctx.page_range is None
    assert dict(ctx.config) == {}
    assert dict(ctx.extra) == {}
    assert ctx.page_markers == ()
    assert ctx.profile is None


def test_context_is_frozen(tmp_path: Path) -> None:
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf")
    with pytest.raises(FrozenInstanceError):
        ctx.format = "epub"


def test_context_freezes_config_and_extra(tmp_path: Path) -> None:
    cfg = {"k": "v"}
    extra = {"a": 1}
    ctx = CleanContext(
        source=_make_source(tmp_path),
        format="pdf",
        config=cfg,
        extra=extra,
    )

    with pytest.raises(TypeError):
        ctx.config["k2"] = "v2"
    with pytest.raises(TypeError):
        ctx.extra["b"] = 2


def test_context_mutating_source_dict_does_not_leak(tmp_path: Path) -> None:
    cfg = {"k": 1}
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf", config=cfg)
    cfg["k"] = 99
    assert ctx.config["k"] == 1


def test_context_requires_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CleanContext(source=None, format="pdf")  # type: ignore[arg-type]


def test_context_rejects_wrong_page_range_type(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        CleanContext(
            source=_make_source(tmp_path),
            format="pdf",
            page_range=(1, 2),  # type: ignore[arg-type]
        )


def test_context_accepts_page_range(tmp_path: Path) -> None:
    rng = PageRange(pages=(1, 2, 3))
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf", page_range=rng)
    assert ctx.page_range is rng


def test_context_accepts_profile_and_markers(tmp_path: Path) -> None:
    ctx = CleanContext(
        source=_make_source(tmp_path),
        format="pdf",
        page_markers=("<!-- page 1 -->", "<!-- page 2 -->"),
        profile="study",
    )
    assert ctx.profile == "study"
    assert ctx.page_markers == ("<!-- page 1 -->", "<!-- page 2 -->")
