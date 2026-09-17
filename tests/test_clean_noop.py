"""Tests for capmd.clean._noop — the identity cleaner (placeholder)."""

from __future__ import annotations

from pathlib import Path

from capmd.clean._noop import NoOpCleaner
from capmd.models import SourceDoc


def _ctx() -> object:
    return SourceDoc(path=Path("/x"), format="pdf", sha256="a" * 64, size_bytes=1)


def test_noop_default_name() -> None:
    c = NoOpCleaner()
    assert c.name == "noop"


def test_noop_custom_name() -> None:
    c = NoOpCleaner(name="placeholder")
    assert c.name == "placeholder"


def test_noop_apply_returns_input() -> None:
    c = NoOpCleaner()
    result = c.apply("hello\nworld", _ctx())
    assert result.text == "hello\nworld"
    assert result.changes == 0


def test_noop_apply_empty() -> None:
    c = NoOpCleaner()
    result = c.apply("", _ctx())
    assert result.text == ""
    assert result.changes == 0


def test_noop_runs_in_pipeline() -> None:
    """NoOpCleaner is a valid Cleaner and can be plugged into a Pipeline."""
    from capmd.clean.pipeline import Pipeline

    p = Pipeline((NoOpCleaner(),))
    md, stats = p.run("foo", _ctx())
    assert md == "foo"
    assert len(stats) == 1
    assert stats[0].changes == 0
