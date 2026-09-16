"""Tests unit del módulo ``capmd.progress`` (H1)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from capmd.progress import (
    StageHandle,
    silent_console_text_io,
    stages,
)


def test_stages_noop_when_quiet() -> None:
    buf = io.StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        with stages(quiet=True, is_tty=True) as prog:
            assert isinstance(prog, StageHandle)
            tid = prog.start("recorte", total=None)
            prog.advance(tid, steps=3)
            prog.stop(tid)
            assert tid == 0
    finally:
        sys.stderr = saved

    assert buf.getvalue() == ""


def test_stages_disabled_when_no_tty() -> None:
    buf = io.StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        with stages(quiet=False, is_tty=False) as prog:
            tid = prog.start("limpieza", total=5)
            prog.advance(tid, steps=5)
            prog.stop(tid)
    finally:
        sys.stderr = saved

    assert buf.getvalue() == ""


def test_stages_writes_to_stderr_when_tty_active() -> None:
    buf = io.StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        with stages(quiet=False, is_tty=True, force_terminal=True) as prog:
            tid = prog.start("recorte", total=None)
            prog.advance(tid, steps=1)
            prog.stop(tid)
            assert tid >= 0
    finally:
        sys.stderr = saved

    out = buf.getvalue()
    assert "recorte" in out


def test_stages_handles_exception_without_leak() -> None:
    buf = io.StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        with (
            pytest.raises(ValueError, match="boom"),
            stages(quiet=False, is_tty=True, force_terminal=True) as prog,
        ):
            prog.start("escritura", total=1)
            raise ValueError("boom")
        # No assert sobre contenido: solo verificamos que el __exit__
        # del contextmanager se ejecutó y no se filtró la excepción.
    finally:
        sys.stderr = saved


def test_stages_nested_no_error() -> None:
    with stages(quiet=True, is_tty=True) as outer:
        outer.start("a")
        with stages(quiet=True, is_tty=True) as inner:
            inner.start("b")
            inner.stop(0)


def test_silent_console_text_io_is_stringio() -> None:
    buf = silent_console_text_io()
    assert isinstance(buf, io.StringIO)
    buf.write("hola")
    assert buf.getvalue() == "hola"


def test_stages_quiet_overrides_tty() -> None:
    """quiet=True gana incluso si is_tty=True (forzamos no-op)."""
    buf = io.StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        with stages(quiet=True, is_tty=True, force_terminal=True) as prog:
            prog.start("recorte")
            prog.start("conversión")
    finally:
        sys.stderr = saved
    assert buf.getvalue() == ""


def test_stages_total_param_accepted() -> None:
    """``total=None`` (spinner) y ``total=N`` (barra determinada) no rompen."""
    with stages(quiet=True) as prog:
        t1 = prog.start("limpieza", total=None)
        assert isinstance(t1, int)
        t2 = prog.start("escritura", total=3)
        assert isinstance(t2, int)


def test_path_only_progress_module_path() -> None:
    """Smoke: el módulo importa sin side effects."""
    p = Path(__file__).parent.parent / "src" / "capmd" / "progress.py"
    assert p.exists()
