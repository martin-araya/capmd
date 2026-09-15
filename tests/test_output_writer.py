"""Tests unitarios de ``capmd.output.writer`` (F1 + F3)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from capmd.errors import IOError as CapmdIOError
from capmd.models import Chapter, PageRange, SourceDoc
from capmd.output.writer import (
    SCHEMA_VERSION,
    CapmdJsonV2,
    book_slug_from,
    build_metadata,
    build_tree_paths,
    chapter_slug_from,
    range_label_from,
    slugify,
    write_output_flat,
    write_output_tree,
)

# --- slugify ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("Rust in Action", "rust-in-action"),
        ("The  Rust Programming Language", "the-rust-programming-language"),
        ("Rust---in-----Action", "rust-in-action"),
        ("  Rust  ", "rust"),
        ("", "untitled"),
        ("!!!", "untitled"),
        ("El Quijote", "el-quijote"),
        ("Programación en Rust", "programacion-en-rust"),
        ("Rust 1.0", "rust-1-0"),
        ("Ownership / Borrowing", "ownership-borrowing"),
    ],
)
def test_slugify(input_text: str, expected: str) -> None:
    assert slugify(input_text) == expected


def test_slugify_truncates_at_max_length() -> None:
    long = "a" * 100
    out = slugify(long, max_length=60)
    assert len(out) <= 60
    assert not out.endswith("-")


def test_slugify_unicode_kept_when_no_combining_marks() -> None:
    # Sin diacríticos NFKD: queda como unicode.
    assert slugify("日本語") == "日本語"


# --- book_slug_from --------------------------------------------------------


def test_book_slug_from_source(tmp_path: Path) -> None:
    src = SourceDoc(path=tmp_path / "Rust in Action.pdf", format="pdf", sha256="a" * 64, size_bytes=1)
    assert book_slug_from(src) == "rust-in-action"


def test_book_slug_from_stdin() -> None:
    assert book_slug_from(None, stdin=True) == "stdin"


# --- chapter_slug_from -----------------------------------------------------


def test_chapter_slug_from_chapter_with_title() -> None:
    ch = Chapter(title="Ownership", level=1, start_page=3, end_page=10, index=3)
    assert chapter_slug_from(chapter=ch, page_range=None) == "cap-03-ownership"


def test_chapter_slug_from_chapter_two_digit_index() -> None:
    ch = Chapter(title="Conclusion", level=1, start_page=200, end_page=205, index=12)
    assert chapter_slug_from(chapter=ch, page_range=None) == "cap-12-conclusion"


def test_chapter_slug_from_chapter_unicode_title() -> None:
    ch = Chapter(title="Propiedad", level=1, start_page=1, end_page=5, index=2)
    assert chapter_slug_from(chapter=ch, page_range=None) == "cap-02-propiedad"


def test_chapter_slug_from_pages_contiguous() -> None:
    rng = PageRange(pages=(45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58))
    assert chapter_slug_from(chapter=None, page_range=rng) == "pages-45-58"


def test_chapter_slug_from_pages_single() -> None:
    rng = PageRange(pages=(42,))
    assert chapter_slug_from(chapter=None, page_range=rng) == "pages-42-42"


def test_chapter_slug_from_pages_non_contiguous_truncated() -> None:
    rng = PageRange(pages=(10, 12, 14, 16, 18, 20, 22, 24, 26, 28))
    slug = chapter_slug_from(chapter=None, page_range=rng)
    assert slug.startswith("pages-10-12-14-16-18-20-22-24")
    assert slug.endswith("-more")


def test_chapter_slug_from_nothing_is_full() -> None:
    assert chapter_slug_from(chapter=None, page_range=None) == "full"


def test_chapter_slug_prefers_chapter_over_pages() -> None:
    ch = Chapter(title="X", level=1, start_page=1, end_page=10, index=4)
    rng = PageRange(pages=(1, 2, 3))
    assert chapter_slug_from(chapter=ch, page_range=rng).startswith("cap-04-")


# --- range_label_from ------------------------------------------------------


def test_range_label_full() -> None:
    assert range_label_from(chapter=None, page_range=None) == "full"


def test_range_label_single_page() -> None:
    assert range_label_from(chapter=None, page_range=PageRange(pages=(7,))) == "7"


def test_range_label_contiguous() -> None:
    assert range_label_from(chapter=None, page_range=PageRange(pages=(1, 2, 3, 4))) == "1-4"


def test_range_label_non_contiguous_truncated() -> None:
    rng = PageRange(pages=(1, 3, 5, 7, 9, 11, 13, 15, 17, 19))
    label = range_label_from(chapter=None, page_range=rng)
    assert label.endswith(",…")


# --- build_tree_paths ------------------------------------------------------


def test_build_tree_paths_non_flat(tmp_path: Path) -> None:
    paths = build_tree_paths(
        tmp_path, book_slug="rust-handbook", chapter_slug="cap-03-ownership", flat=False
    )
    assert paths.markdown_path == tmp_path / "rust-handbook" / "cap-03-ownership" / "cap-03-ownership.md"
    assert paths.images_dir == tmp_path / "rust-handbook" / "cap-03-ownership" / "images"
    assert paths.capmd_json_path == tmp_path / "rust-handbook" / "cap-03-ownership" / "capmd.json"
    assert paths.layout == "tree"


def test_build_tree_paths_flat() -> None:
    paths = build_tree_paths(Path("/x"), book_slug="rust-handbook", chapter_slug="cap-03", flat=True)
    assert paths.markdown_path == Path("/x/rust-handbook.md")
    assert paths.images_dir is None
    assert paths.capmd_json_path is None
    assert paths.layout == "flat"


# --- CapmdJsonV2 -----------------------------------------------------------


def test_capmd_json_v2_round_trip() -> None:
    payload = CapmdJsonV2(
        book_slug="rust-handbook",
        chapter_slug="cap-03-ownership",
        title="Ownership",
        source_file="Rust Handbook.pdf",
        source_sha256="abc" * 21 + "abcd",
        pages=(45, 46, 47, 48),
        range_label="45-48",
        chapter={"index": 3, "title": "Ownership", "level": 1, "start_page": 45, "end_page_inclusive": 60},
        generated_at="2026-09-15T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="0.1.7",
        images_dir="images",
        layout="tree",
        elapsed_seconds=1.5,
        cleaners_applied=("whitespace", "headers"),
        cleaner_stats=(
            {"name": "whitespace", "enabled": True, "changes": 5, "duration_ms": 12.3, "error": None},
        ),
        figures=(
            {"chapter_index": 3, "index": 1, "path": "images/fig-03-01.png",
             "page": 45, "bbox": [0.1, 0.2, 0.3, 0.4], "caption": None,
             "alt_text": None, "width": 320, "height": 240},
        ),
        warnings=(),
    )
    serialized = payload.as_json()
    parsed = json.loads(serialized)
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["book_slug"] == "rust-handbook"
    assert parsed["chapter_slug"] == "cap-03-ownership"
    assert parsed["title"] == "Ownership"
    assert parsed["markitdown_version"] == "0.1.7"
    assert parsed["pages"] == [45, 46, 47, 48]
    assert parsed["layout"] == "tree"
    assert parsed["images_dir"] == "images"
    assert parsed["chapter"]["index"] == 3
    assert parsed["elapsed_seconds"] == 1.5
    assert parsed["cleaner_stats"][0]["changes"] == 5
    assert parsed["figures"][0]["path"] == "images/fig-03-01.png"


def test_capmd_json_v2_stdin() -> None:
    payload = CapmdJsonV2(
        book_slug="stdin",
        chapter_slug="full",
        title="stdin",
        source_file=None,
        source_sha256=None,
        pages=None,
        range_label="full",
        chapter=None,
        generated_at="2026-09-15T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="unknown",
        images_dir=None,
        layout="flat",
        elapsed_seconds=0.0,
    )
    parsed = json.loads(payload.as_json())
    assert parsed["source_file"] is None
    assert parsed["pages"] is None
    assert parsed["chapter"] is None
    assert parsed["cleaner_stats"] == []
    assert parsed["figures"] == []
    assert parsed["warnings"] == []


def test_capmd_json_v2_default_lists_are_empty() -> None:
    """F3: stats y figures siempre presentes como listas, vacías por default."""
    payload = CapmdJsonV2(
        book_slug="b", chapter_slug="c", title="t",
        source_file=None, source_sha256=None,
        pages=None, range_label="full", chapter=None,
        generated_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0", markitdown_version="unknown",
        images_dir=None, layout="tree",
        elapsed_seconds=0.0,
    )
    parsed = json.loads(payload.as_json())
    assert parsed["cleaner_stats"] == []
    assert parsed["figures"] == []
    assert parsed["warnings"] == []


def test_capmd_json_sorted_keys_deterministic() -> None:
    """Mismo input → mismo output (predecible para diffs en CI)."""
    payload = CapmdJsonV2(
        book_slug="b", chapter_slug="c", title="t",
        source_file=None, source_sha256=None,
        pages=None, range_label="full", chapter=None,
        generated_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0", markitdown_version="unknown",
        images_dir=None, layout="tree", elapsed_seconds=0.0,
    )
    a = payload.as_json()
    b = payload.as_json()
    assert a == b


# --- build_metadata helper --------------------------------------------------


def test_build_metadata_with_chapter(tmp_path: Path) -> None:
    src = SourceDoc(
        path=tmp_path / "Rust Handbook.pdf",
        format="pdf",
        sha256="d" * 64,
        size_bytes=1024,
    )
    ch = Chapter(title="Ownership", level=1, start_page=45, end_page=60, index=3)
    meta = build_metadata(
        source=src,
        stdin=False,
        book_slug="rust-handbook",
        chapter_slug="cap-03-ownership",
        chapter=ch,
        page_range=None,
        images_dir_relative="images",
        layout="tree",
        cleaners_applied=("whitespace",),
        now=datetime(2026, 9, 15, 0, 0, 0),
    )
    assert meta.source_file == "Rust Handbook.pdf"
    assert meta.source_sha256 == "d" * 64
    assert meta.pages == tuple(range(45, 60))
    assert meta.range_label == "45-59"
    assert meta.chapter is not None
    assert meta.chapter["title"] == "Ownership"
    assert meta.generated_at == "2026-09-15T00:00:00Z"


def test_build_metadata_stdin() -> None:
    meta = build_metadata(
        source=None,
        stdin=True,
        book_slug="stdin",
        chapter_slug="full",
        chapter=None,
        page_range=None,
        images_dir_relative=None,
        layout="flat",
    )
    assert meta.source_file is None
    assert meta.pages is None
    assert meta.chapter is None


# --- write_output_tree -----------------------------------------------------


def test_write_output_tree_creates_three_artifacts(tmp_path: Path) -> None:
    paths = build_tree_paths(
        tmp_path, book_slug="book", chapter_slug="cap-01-intro", flat=False
    )
    metadata = CapmdJsonV2(
        book_slug="book",
        chapter_slug="cap-01-intro",
        title="Intro",
        source_file="book.pdf",
        source_sha256="a" * 64,
        pages=(1, 2),
        range_label="1-2",
        chapter=None,
        generated_at="2026-09-15T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="0.1.7",
        images_dir="images",
        layout="tree",
        elapsed_seconds=0.5,
    )
    result = write_output_tree(paths, markdown="# hi\n", metadata=metadata)
    assert result.markdown_path.exists()
    assert result.images_dir is not None and result.images_dir.is_dir()
    assert result.capmd_json_path is not None and result.capmd_json_path.exists()
    assert result.markdown_path.read_text(encoding="utf-8") == "# hi\n"
    parsed = json.loads(result.capmd_json_path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["book_slug"] == "book"
    assert parsed["title"] == "Intro"


def test_write_output_tree_refuses_existing_dir(tmp_path: Path) -> None:
    paths = build_tree_paths(
        tmp_path, book_slug="book", chapter_slug="cap-01-intro", flat=False
    )
    paths.markdown_path.parent.mkdir(parents=True)

    with pytest.raises(CapmdIOError):
        write_output_tree(
            paths,
            markdown="x",
            metadata=CapmdJsonV2(
                book_slug="book", chapter_slug="cap-01-intro", title="Intro",
                source_file=None, source_sha256=None,
                pages=None, range_label="full", chapter=None,
                generated_at="2026-09-15T00:00:00Z", capmd_version="0.1.0",
                markitdown_version="0.1.7",
                images_dir="images", layout="tree", elapsed_seconds=0.0,
            ),
        )


# --- write_output_flat -----------------------------------------------------


def test_write_output_flat_only_writes_markdown(tmp_path: Path) -> None:
    paths = build_tree_paths(tmp_path, book_slug="book", chapter_slug="cap-01", flat=True)
    out_path = write_output_flat(paths, markdown="# only md\n")
    assert out_path == tmp_path / "book.md"
    assert out_path.read_text(encoding="utf-8") == "# only md\n"
    # No subcarpetas, no JSON, no images/.
    assert list(tmp_path.iterdir()) == [out_path]


def test_write_output_flat_refuses_existing_file(tmp_path: Path) -> None:
    paths = build_tree_paths(tmp_path, book_slug="book", chapter_slug="cap-01", flat=True)
    paths.markdown_path.write_text("# existente\n", encoding="utf-8")
    with pytest.raises(CapmdIOError):
        write_output_flat(paths, markdown="# nuevo\n")
