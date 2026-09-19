"""Tests del manejo de PermissionError (FIX-6)."""

from __future__ import annotations

import errno
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from capmd.errors import IOError as CapmdIOError
from capmd.errors import PermissionDenied
from capmd.output._atomic import _format_permission_hint
from capmd.output.writer import _write_text


# --- unit: _format_permission_hint ---


def test_format_permission_hint_with_filename() -> None:
    """FIX-6: hint menciona el directorio del path que falló."""
    err = PermissionError(errno.EACCES, "Permission denied", "/readonly/foo.md")
    hint = _format_permission_hint(err)
    assert "/readonly" in hint
    assert "escribible" in hint


def test_format_permission_hint_with_filename2() -> None:
    """FIX-6: hint usa ``filename2`` cuando ``filename`` es None
    (caso de link/rename/copy). Apunta al parent del dest."""
    err = OSError(errno.EACCES, "Permission denied")
    err.filename = None
    err.filename2 = "/readonly/dest"
    hint = _format_permission_hint(err)
    # El parent del dest es donde el usuario necesita write perms.
    assert "/readonly" in hint


def test_format_permission_hint_no_filename_fallback() -> None:
    """FIX-6: sin filename, hint genérico."""
    err = PermissionError(errno.EACCES, "Permission denied")
    hint = _format_permission_hint(err)
    assert "permisos" in hint.lower() or "escribible" in hint


def test_format_permission_hint_dir_target_keeps_full_path() -> None:
    """FIX-6: si ``filename`` apunta a un dir, hint apunta al parent."""
    err = PermissionError(errno.EACCES, "Permission denied", "/readonly/dir")
    hint = _format_permission_hint(err)
    assert "/readonly" in hint


# --- unit: _write_text raises PermissionDenied ---


def test_write_text_permission_error_raises_permissiondenied(
    tmp_path: Path,
) -> None:
    """FIX-6: ``_write_text`` con PermissionError → PermissionDenied rc=5."""
    target = tmp_path / "file.md"

    def boom(*_args: object, **_kwargs: object) -> int:
        raise PermissionError(errno.EACCES, "Permission denied", str(target))

    with patch.object(Path, "write_text", side_effect=boom):
        with pytest.raises(PermissionDenied) as excinfo:
            _write_text(target, "x")

    assert excinfo.value.exit_code == 5
    assert str(target.parent) in (excinfo.value.hint or "")


def test_write_text_other_oserror_raises_ioerror(tmp_path: Path) -> None:
    """FIX-6 regresión: otros OSError siguen siendo CapmdIOError (rc=7)."""
    target = tmp_path / "file.md"

    with patch.object(
        Path,
        "write_text",
        side_effect=OSError(errno.ENOSPC, "No space left"),
    ):
        with pytest.raises(CapmdIOError) as excinfo:
            _write_text(target, "x")

    assert excinfo.value.exit_code == 7


# --- CLI integration: rc=5 with permission error (mocked, CI-portable) ---


def test_convert_o_permission_error_exits_5(tmp_path: Path) -> None:
    """FIX-6 integración: capmd convert con -o en dir read-only →
    rc=5 con hint específico del path real (no 'images/')."""
    from tests.fixtures import build as build_mod

    pdf = build_mod.build_headings_pdf(tmp_path / "doc.pdf")
    target_md = tmp_path / "readonly" / "foo.md"

    def fail_write(*_args: object, **_kwargs: object) -> int:
        raise PermissionError(
            errno.EACCES, "Permission denied", str(target_md)
        )

    # Mockear write_text de TODOS los paths — más simple que mockear
    # selectivamente. El primer write_text falla con PermissionError.
    with patch.object(Path, "write_text", side_effect=fail_write):
        r = CliRunner().invoke(
            app, ["convert", str(pdf), "-o", str(target_md)]
        )

    assert r.exit_code == 5
    assert "Traceback" not in r.stderr
    # El hint debe mencionar el path real, no 'images/' simbólico.
    assert "foo.md" in r.stderr or str(tmp_path) in r.stderr


def test_convert_out_permission_error_exits_5(tmp_path: Path) -> None:
    """FIX-6 integración: capmd convert --out en dir read-only →
    rc=5 con hint específico."""
    from tests.fixtures import build as build_mod

    pdf = build_mod.build_headings_pdf(tmp_path / "doc.pdf")
    out_dir = tmp_path / "readonly_dir"
    out_dir.mkdir()

    real_write_text = Path.write_text

    def selective_fail(self: Path, *args: object, **kwargs: object) -> int:
        # Solo falla si es write de un .md o .json (los archivos reales).
        if str(self).endswith((".md", ".json")):
            raise PermissionError(
                errno.EACCES, "Permission denied", str(self)
            )
        return real_write_text(self, *args, **kwargs)  # pragma: no cover

    with patch.object(Path, "write_text", new=selective_fail):
        r = CliRunner().invoke(
            app, ["convert", str(pdf), "--out", str(out_dir)]
        )

    assert r.exit_code == 5
    assert "Traceback" not in r.stderr
