"""Tests unitarios del snapshot de output crudo (B6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from capmd.errors import IOError
from capmd.output.snapshot import write_raw_snapshot


def test_write_raw_snapshot_creates_capmd_dir(tmp_path: Path) -> None:
    out = tmp_path / "x.md"
    out.write_text("dummy", encoding="utf-8")

    snapshot = write_raw_snapshot("hello", output_path=out)

    assert snapshot == tmp_path / ".capmd" / "raw.md"
    assert snapshot.exists()
    assert snapshot.read_text(encoding="utf-8") == "hello"
    assert (tmp_path / ".capmd").is_dir()


def test_write_raw_snapshot_uses_output_parent(tmp_path: Path) -> None:
    """El snapshot vive junto al archivo de output, no en cwd."""
    nested = tmp_path / "nested"
    nested.mkdir()
    out = nested / "x.md"
    out.write_text("ignored", encoding="utf-8")

    snapshot = write_raw_snapshot("raw content", output_path=out)

    assert snapshot.parent.parent == nested
    assert snapshot.read_text(encoding="utf-8") == "raw content"


def test_write_raw_snapshot_falls_back_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    snapshot = write_raw_snapshot("from stdin", output_path=None)
    assert snapshot == tmp_path / ".capmd" / "raw.md"
    assert snapshot.read_text(encoding="utf-8") == "from stdin"


def test_write_raw_snapshot_overwrites(tmp_path: Path) -> None:
    out = tmp_path / "x.md"
    out.write_text("ignored", encoding="utf-8")

    write_raw_snapshot("first", output_path=out)
    second = write_raw_snapshot("second", output_path=out)

    assert second.read_text(encoding="utf-8") == "second"


def test_write_raw_snapshot_raises_permission_denied_on_permissionerror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-6: ``write_raw_snapshot`` con PermissionError →
    PermissionDenied(rc=5) con hint accionable."""
    from capmd.errors import PermissionDenied

    out = tmp_path / "x.md"
    out.write_text("ignored", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def _boom(*_args: object, **_kwargs: object) -> int:
        # PermissionError sin filename: el hint cae al fallback genérico
        # pero sigue siendo accionable. Lo importante es la traducción a
        # PermissionDenied(rc=5) en vez de CapmdIOError(rc=7).
        raise PermissionError(13, "denegado")

    with patch.object(Path, "write_text", side_effect=_boom), pytest.raises(PermissionDenied) as excinfo:
        write_raw_snapshot("x", output_path=out)

    assert excinfo.value.exit_code == 5
    # El hint es una de las dos formas (con filename o fallback).
    hint = excinfo.value.hint or ""
    assert "escribible" in hint or "permisos" in hint


def test_write_raw_snapshot_raises_io_error_on_other_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-6 regresión: OSError NO-PermissionError sigue siendo
    IOError (rc=7) con hint genérico."""
    out = tmp_path / "x.md"
    out.write_text("ignored", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def _boom(*_args: object, **_kwargs: object) -> int:
        raise OSError(28, "No space left")

    import errno
    with patch.object(Path, "write_text", side_effect=_boom), pytest.raises(IOError) as excinfo:
        write_raw_snapshot("x", output_path=out)

    assert excinfo.value.exit_code == 7
    assert "No space" in (excinfo.value.hint or "")


# --- FIX-4: tree mode (--out) ---


def test_write_raw_snapshot_tree_mode(tmp_path: Path) -> None:
    """FIX-4: con ``out_dir`` + ``book_slug`` + ``chapter_slug``,
    el snapshot vive en ``<out>/<book>/<chapter>/.capmd/raw.md``."""
    snapshot = write_raw_snapshot(
        "raw tree content",
        out_dir=tmp_path,
        book_slug="b",
        chapter_slug="c",
    )
    expected = tmp_path / "b" / "c" / ".capmd" / "raw.md"
    assert snapshot == expected
    assert snapshot.exists()
    assert snapshot.read_text(encoding="utf-8") == "raw tree content"
    assert (tmp_path / "b" / "c" / ".capmd").is_dir()


def test_write_raw_snapshot_tree_mode_does_not_pollute_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-4: tree mode no debe crear ``.capmd/`` en el CWD del proceso."""
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)

    write_raw_snapshot(
        "raw",
        out_dir=tmp_path / "out",
        book_slug="b",
        chapter_slug="c",
    )

    # CWD debe quedar intacto (no hay .capmd/ suelto).
    assert not (cwd_dir / ".capmd").exists()


def test_write_raw_snapshot_tree_mode_overwrites(tmp_path: Path) -> None:
    """FIX-4: 2da invocación sobrescribe el snapshot (consistente con
    comportamiento single-file)."""
    args = dict(
        out_dir=tmp_path,
        book_slug="b",
        chapter_slug="c",
    )
    write_raw_snapshot("first", **args)
    snapshot = write_raw_snapshot("second", **args)
    assert snapshot.read_text(encoding="utf-8") == "second"
