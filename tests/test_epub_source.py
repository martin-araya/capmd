"""Tests de :mod:`capmd.sources.epub` (fase C9).

Cubre lectura del spine, lookup por título (vía TOC), extracción del
XHTML de un capítulo a archivo temporal y manejo de EPUB inválido.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.errors import SourceNotFound
from capmd.models import Chapter
from capmd.sources.epub import read_outline, slice_epub
from tests.fixtures import build


def _epub(tmp_path: Path) -> Path:
    return build.build_epub_with_3_chapters(tmp_path / "demo.epub")


def test_read_outline_returns_three_chapters(tmp_path: Path) -> None:
    chapters = read_outline(_epub(tmp_path))
    assert len(chapters) == 3


def test_chapter_titles_from_nav(tmp_path: Path) -> None:
    chapters = read_outline(_epub(tmp_path))
    titles = [c.title for c in chapters]
    assert titles == ["Capitulo 1", "Capitulo 2", "Capitulo 3"]


def test_chapter_index_sequential(tmp_path: Path) -> None:
    chapters = read_outline(_epub(tmp_path))
    assert [c.index for c in chapters] == [1, 2, 3]


def test_chapter_level_is_one_and_page_range_consistent(tmp_path: Path) -> None:
    chapters = read_outline(_epub(tmp_path))
    for ch in chapters:
        assert ch.level == 1
        assert ch.end_page == ch.start_page + 1


def test_slice_epub_extracts_correct_xhtml(tmp_path: Path) -> None:
    chapters = read_outline(_epub(tmp_path))
    target = next(c for c in chapters if c.index == 2)
    out = slice_epub(_epub(tmp_path), target)
    try:
        text = out.read_bytes().decode("utf-8")
        assert "Capitulo 2" in text
        assert "MARKER-CH-2-CONTENT" in text
        assert "MARKER-CH-1-CONTENT" not in text
        assert "MARKER-CH-3-CONTENT" not in text
    finally:
        out.unlink(missing_ok=True)


def test_slice_epub_tempfile_can_be_unlinked(tmp_path: Path) -> None:
    chapters = read_outline(_epub(tmp_path))
    target = chapters[0]
    out = slice_epub(_epub(tmp_path), target)
    assert out.exists()
    out.unlink(missing_ok=True)
    assert not out.exists()
    # idempotente
    out.unlink(missing_ok=True)


def test_slice_epub_out_of_range_raises(tmp_path: Path) -> None:
    read_outline(_epub(tmp_path))
    bogus = Chapter(
        title="x", level=1, start_page=99, end_page=100, index=99
    )
    with pytest.raises(ValueError, match="fuera de rango"):
        slice_epub(_epub(tmp_path), bogus)


def test_read_outline_corrupt_epub_raises_source_not_found(tmp_path: Path) -> None:
    bad = tmp_path / "broken.epub"
    bad.write_bytes(b"not an epub")
    with pytest.raises(SourceNotFound):
        read_outline(bad)
