"""Tests unitarios de la resolución de colisiones de destino (F8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.errors import IOError as CapmdIOError
from capmd.output.writer import (
    resolve_destination_collision,
    write_output_flat,
    write_output_tree,
)

# --- resolve_destination_collision ----------------------------------------


def test_resolve_destination_returns_same_when_missing(tmp_path: Path) -> None:
    out = tmp_path / "missing.md"
    assert resolve_destination_collision(out, force=False, suffix=False) == out


def test_resolve_destination_error_with_clear_hint(tmp_path: Path) -> None:
    out = tmp_path / "exists.md"
    out.write_text("x")
    with pytest.raises(CapmdIOError) as exc:
        resolve_destination_collision(out, force=False, suffix=False)
    # El hint va en ``exc.hint``, no en str(exc).
    assert exc.value.hint is not None
    assert "--force" in exc.value.hint
    assert "--suffix" in exc.value.hint


def test_resolve_force_returns_same_for_existing(tmp_path: Path) -> None:
    """``--force`` no renombra; el caller es responsable de borrar antes."""
    out = tmp_path / "exists.md"
    out.write_text("x")
    resolved = resolve_destination_collision(out, force=True, suffix=False)
    assert resolved == out


def test_resolve_suffix_first_version(tmp_path: Path) -> None:
    """``out.md`` existe → ``--suffix`` devuelve ``out-1.md``."""
    out = tmp_path / "out.md"
    out.write_text("x")
    resolved = resolve_destination_collision(out, force=False, suffix=True)
    assert resolved == tmp_path / "out-1.md"


def test_resolve_suffix_increments_when_already_versioned(tmp_path: Path) -> None:
    out = tmp_path / "out.md"
    out.write_text("x")
    (tmp_path / "out-1.md").write_text("x")
    (tmp_path / "out-2.md").write_text("x")
    resolved = resolve_destination_collision(out, force=False, suffix=True)
    assert resolved == tmp_path / "out-3.md"


def test_resolve_suffix_chains_for_directory(tmp_path: Path) -> None:
    """``out/`` existe → ``--suffix`` devuelve ``out-1/``."""
    out = tmp_path / "out"
    out.mkdir()
    resolved = resolve_destination_collision(
        out, force=False, suffix=True, kind="dir"
    )
    assert resolved == tmp_path / "out-1"


def test_resolve_suffix_chains_multiple_versions_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "out-1").mkdir()
    (tmp_path / "out-2").mkdir()
    resolved = resolve_destination_collision(
        out, force=False, suffix=True, kind="dir"
    )
    assert resolved == tmp_path / "out-3"


def test_resolve_force_and_suffix_together_raises(tmp_path: Path) -> None:
    out = tmp_path / "x.md"
    out.write_text("x")
    with pytest.raises(ValueError, match="mutuamente excluyentes"):
        resolve_destination_collision(out, force=True, suffix=True)


def test_resolve_error_msg_mentions_dir_vs_file(tmp_path: Path) -> None:
    """El message diferencia entre archivo y directorio (decorativo)."""
    err_file = tmp_path / "f.md"
    err_file.write_text("x")
    with pytest.raises(CapmdIOError) as exc:
        resolve_destination_collision(err_file, force=False, suffix=False, kind="file")
    assert "archivo" in str(exc.value)

    err_dir = tmp_path / "d"
    err_dir.mkdir()
    with pytest.raises(CapmdIOError) as exc:
        resolve_destination_collision(err_dir, force=False, suffix=False, kind="dir")
    assert "directorio" in str(exc.value)


# --- write_output_flat con --force ----------------------------------------


def test_write_output_flat_force_overwrites_existing(tmp_path: Path) -> None:
    from capmd.output.writer import OutputPaths

    out = tmp_path / "out.md"
    paths = OutputPaths(
        markdown_path=out, images_dir=None, capmd_json_path=None, layout="flat"
    )
    write_output_flat(paths, markdown="first")
    assert out.read_text(encoding="utf-8") == "first"

    write_output_flat(paths, markdown="second", force=True)
    assert out.read_text(encoding="utf-8") == "second"


def test_write_output_tree_force_overwrites_existing(tmp_path: Path) -> None:
    """``write_output_tree`` con ``force=True`` borra y recrea."""
    from capmd.output.writer import CapmdJsonV2, OutputPaths

    chapter_dir = tmp_path / "book" / "chap"
    out_md = chapter_dir / "chap.md"
    out_json = chapter_dir / "capmd.json"
    images = chapter_dir / "images"

    paths = OutputPaths(
        markdown_path=out_md,
        images_dir=images,
        capmd_json_path=out_json,
        layout="tree",
    )
    meta = CapmdJsonV2(
        book_slug="b",
        chapter_slug="chap",
        title="t",
        source_file="x.pdf",
        source_sha256="0" * 64,
        pages=(1,),
        range_label="1",
        chapter=None,
        generated_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="0.1.0",
        images_dir="images",
        layout="tree",
        elapsed_seconds=0.0,
    )
    # 1st write.
    write_output_tree(paths, markdown="first", metadata=meta)
    assert out_md.read_text(encoding="utf-8") == "first"

    # 2nd con force=True → borra y recrea.
    write_output_tree(
        paths, markdown="second", metadata=meta, force=True
    )
    assert out_md.read_text(encoding="utf-8") == "second"


def test_write_output_tree_force_false_still_raises(tmp_path: Path) -> None:
    from capmd.output.writer import CapmdJsonV2, OutputPaths

    chapter_dir = tmp_path / "book" / "chap"
    out_md = chapter_dir / "chap.md"
    out_json = chapter_dir / "capmd.json"
    images = chapter_dir / "images"

    paths = OutputPaths(
        markdown_path=out_md,
        images_dir=images,
        capmd_json_path=out_json,
        layout="tree",
    )
    meta = CapmdJsonV2(
        book_slug="b",
        chapter_slug="chap",
        title="t",
        source_file="x.pdf",
        source_sha256="0" * 64,
        pages=(1,),
        range_label="1",
        chapter=None,
        generated_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="0.1.0",
        images_dir="images",
        layout="tree",
        elapsed_seconds=0.0,
    )
    write_output_tree(paths, markdown="first", metadata=meta)
    with pytest.raises(CapmdIOError, match="ya existe"):
        write_output_tree(paths, markdown="second", metadata=meta)  # no force
