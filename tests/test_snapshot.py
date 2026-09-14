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


def test_write_raw_snapshot_raises_io_error_on_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "x.md"
    out.write_text("ignored", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def _boom(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("denegado")

    with patch.object(Path, "write_text", side_effect=_boom), pytest.raises(IOError) as excinfo:
        write_raw_snapshot("x", output_path=out)

    assert excinfo.value.exit_code == 7
    assert "denegado" in (excinfo.value.hint or "")
