"""Tests unitarios de ``CapmdJsonV2`` (F3) y el round-trip de regeneración de FM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from capmd.models import Chapter, Figure, SourceDoc
from capmd.output.frontmatter import (
    build_front_matter_fields,
    front_matter_fields_from_capmd_json,
    prepend_front_matter,
    render_front_matter,
)
from capmd.output.writer import (
    SCHEMA_VERSION,
    CapmdJsonV2,
    _figure_to_dict,
    build_metadata,
)

# --- SCHEMA_VERSION --------------------------------------------------------


def test_schema_version_is_two() -> None:
    assert SCHEMA_VERSION == 2


# --- CapmdJsonV2 shape (F3: 20 fields) --------------------------------------


def test_capmd_json_v2_has_20_keys() -> None:
    payload = CapmdJsonV2(
        book_slug="b",
        chapter_slug="c",
        title="t",
        source_file=None,
        source_sha256=None,
        pages=None,
        range_label="full",
        chapter=None,
        generated_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0",
        markitdown_version="0.1.7",
        images_dir=None,
        layout="tree",
        elapsed_seconds=1.0,
    )
    parsed = json.loads(payload.as_json())
    expected = {
        "book_slug", "chapter", "chapter_slug", "cleaner_stats",
        "cleaners_applied", "capmd_version", "elapsed_seconds", "figures",
        "generated_at", "images_dir", "layout", "markitdown_version",
        "pages", "range_label", "schema_version", "source_file",
        "source_sha256", "title", "warnings",
    }
    assert set(parsed.keys()) == expected


def test_capmd_json_v2_elapsed_seconds_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="elapsed_seconds"):
        CapmdJsonV2(
            book_slug="b", chapter_slug="c", title="t",
            source_file=None, source_sha256=None, pages=None,
            range_label="full", chapter=None,
            generated_at="2026-01-01T00:00:00Z",
            capmd_version="0.1.0", markitdown_version="unknown",
            images_dir=None, layout="tree", elapsed_seconds=-0.1,
        )


def test_capmd_json_v2_serializes_schema_version_2() -> None:
    payload = CapmdJsonV2(
        book_slug="b", chapter_slug="c", title="t",
        source_file=None, source_sha256=None, pages=None,
        range_label="full", chapter=None,
        generated_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0", markitdown_version="unknown",
        images_dir=None, layout="tree", elapsed_seconds=0.0,
    )
    parsed = json.loads(payload.as_json())
    assert parsed["schema_version"] == 2


def test_capmd_json_v2_lists_are_always_present() -> None:
    """F3: stats, figures y warnings siempre como listas (vacías si vacías)."""
    payload = CapmdJsonV2(
        book_slug="b", chapter_slug="c", title="t",
        source_file=None, source_sha256=None, pages=None,
        range_label="full", chapter=None,
        generated_at="2026-01-01T00:00:00Z",
        capmd_version="0.1.0", markitdown_version="unknown",
        images_dir=None, layout="tree", elapsed_seconds=0.0,
    )
    parsed = json.loads(payload.as_json())
    assert parsed["cleaner_stats"] == []
    assert parsed["figures"] == []
    assert parsed["warnings"] == []


# --- _figure_to_dict (path relativo + campos útiles) -----------------------


def test_figure_to_dict_path_is_relative(tmp_path: Path) -> None:
    fig = Figure(
        chapter_index=3, index=1,
        path=tmp_path / "images" / "fig-03-01.png",
        page=10, bbox=(0.1, 0.2, 0.3, 0.4),
        caption="Figure caption", alt_text="alt", width=320, height=240,
    )
    d = _figure_to_dict(fig, images_dir_relative="images")
    assert d["path"] == "images/fig-03-01.png"
    assert d["chapter_index"] == 3
    assert d["index"] == 1
    assert d["page"] == 10
    assert d["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert d["caption"] == "Figure caption"
    assert d["alt_text"] == "alt"
    assert d["width"] == 320
    assert d["height"] == 240


def test_figure_to_dict_handles_null_bbox() -> None:
    fig = Figure(
        chapter_index=1, index=1,
        path=Path("/tmp/fig.png"), page=1, bbox=None,
        caption=None, alt_text=None, width=None, height=None,
    )
    d = _figure_to_dict(fig, images_dir_relative="images")
    assert d["bbox"] is None
    assert d["width"] is None
    assert d["height"] is None


# --- build_metadata title fallback chain ------------------------------------


def test_build_metadata_title_falls_back_to_book_slug(tmp_path: Path) -> None:
    src = SourceDoc(
        path=tmp_path / "Rust.pdf", format="pdf",
        sha256="x" * 64, size_bytes=1,
    )
    meta = build_metadata(
        source=src, stdin=False,
        book_slug="rust-handbook", chapter_slug="full",
        chapter=None, page_range=None,
        images_dir_relative=None, layout="tree",
    )
    assert meta.title == "rust-handbook"


def test_build_metadata_title_falls_back_to_chapter_title(tmp_path: Path) -> None:
    src = SourceDoc(
        path=tmp_path / "Rust.pdf", format="pdf",
        sha256="x" * 64, size_bytes=1,
    )
    ch = Chapter(title="Ownership", level=1, start_page=45, end_page=60, index=3)
    meta = build_metadata(
        source=src, stdin=False,
        book_slug="rust-handbook", chapter_slug="cap-03",
        chapter=ch, page_range=None,
        images_dir_relative="images", layout="tree",
        title=None,  # explicit: use fallback chain
    )
    assert meta.title == "Ownership"


def test_build_metadata_title_from_callers_explicit_value(tmp_path: Path) -> None:
    src = SourceDoc(
        path=tmp_path / "Rust.pdf", format="pdf",
        sha256="x" * 64, size_bytes=1,
    )
    ch = Chapter(title="Ownership", level=1, start_page=45, end_page=60, index=3)
    meta = build_metadata(
        source=src, stdin=False,
        book_slug="rust-handbook", chapter_slug="cap-03",
        chapter=ch, page_range=None,
        images_dir_relative="images", layout="tree",
        title="My H1",
    )
    assert meta.title == "My H1"


# --- build_metadata stats/figures inclusion --------------------------------


def test_build_metadata_serializes_stats_and_figures(tmp_path: Path) -> None:
    src = SourceDoc(
        path=tmp_path / "Rust.pdf", format="pdf",
        sha256="x" * 64, size_bytes=1,
    )
    fig = Figure(
        chapter_index=3, index=1, path=tmp_path / "fig.png",
        page=10, bbox=None, caption=None, alt_text=None,
        width=100, height=100,
    )
    stats = (
        {"name": "whitespace", "enabled": True, "changes": 5,
         "duration_ms": 1.0, "error": None},
    )
    meta = build_metadata(
        source=src, stdin=False,
        book_slug="rust-handbook", chapter_slug="cap-03",
        chapter=None, page_range=None,
        images_dir_relative="images", layout="tree",
        cleaner_stats=stats, figures=(fig,), elapsed_seconds=2.5,
    )
    parsed = json.loads(meta.as_json())
    assert parsed["cleaner_stats"][0]["changes"] == 5
    assert parsed["figures"][0]["path"].endswith("fig.png")
    assert parsed["elapsed_seconds"] == 2.5


# --- Literal test of F3: regeneración del FM desde JSON --------------------


def _sample_dict() -> dict[str, Any]:
    """Construye un dict CapmdJsonV2 con todos los campos poblados."""
    return {
        "book_slug": "rust-handbook",
        "chapter_slug": "cap-03-ownership",
        "title": "Ownership",
        "source_file": "Rust Handbook.pdf",
        "source_sha256": "abc" * 21 + "abcd",
        "pages": [45, 46, 47, 48],
        "range_label": "45-48",
        "chapter": {"index": 3, "title": "Ownership", "level": 1,
                     "start_page": 45, "end_page_inclusive": 60},
        "generated_at": "2026-09-15T00:00:00Z",
        "capmd_version": "0.1.0",
        "markitdown_version": "0.1.7",
        "images_dir": "images",
        "layout": "tree",
        "elapsed_seconds": 1.5,
        "cleaner_stats": [{"name": "whitespace", "enabled": True,
                            "changes": 5, "duration_ms": 12.3, "error": None}],
        "figures": [],
        "warnings": [],
        "cleaners_applied": ["whitespace", "headers"],
        "schema_version": 2,
    }


def test_front_matter_fields_from_capmd_json_round_trip() -> None:
    """Test literal del roadmap F3.

    Dado un ``capmd.json``, el helper de regeneración produce un dict
    que, al renderizarlo, genera el **mismo bloque YAML** que
    ``build_front_matter_fields`` produce desde los inputs originales.

    La comparación es a nivel de YAML serializado (con ``yaml.safe_load``
    del bloque parseado), no a nivel de dict crudo, porque los nombres
    de keys difieren entre el dict del FM (``book``, ``chapter``) y el
    dict interno del helper (``book_slug``, ``chapter_slug``).
    """
    import re as _re

    import yaml as _yaml

    json_payload = _sample_dict()
    original_fm = build_front_matter_fields(
        title="Ownership",
        book_slug="rust-handbook",
        chapter_slug="cap-03-ownership",
        pages=[45, 46, 47, 48],
        source_file="Rust Handbook.pdf",
        source_sha256="abc" * 21 + "abcd",
        converted_at="2026-09-15T00:00:00Z",
        capmd_version="0.1.0",
        cleaners_applied=("whitespace", "headers"),
        markitdown_version="0.1.7",
    )
    regenerated_fm = front_matter_fields_from_capmd_json(json_payload)

    def _parse_block(text: str) -> dict[str, Any]:
        m = _re.match(r"\A---\n(.*?)\n---\n", text, _re.DOTALL)
        assert m is not None
        return _yaml.safe_load(m.group(1))

    rendered_original = render_front_matter(original_fm)
    rendered_regenerated = render_front_matter(regenerated_fm)
    parsed_original = _parse_block(rendered_original)
    parsed_regenerated = _parse_block(rendered_regenerated)
    assert parsed_original == parsed_regenerated


def test_front_matter_fields_from_capmd_json_emits_same_yaml() -> None:
    """Generar el FM block desde el JSON produce el mismo YAML que el path original."""
    json_payload = _sample_dict()
    fm_from_json = front_matter_fields_from_capmd_json(json_payload)
    rendered_json = render_front_matter(fm_from_json)
    import re as _re

    import yaml as _yaml

    def _parse_block(text: str) -> dict[str, Any]:
        m = _re.match(r"\A---\n(.*?)\n---\n", text, _re.DOTALL)
        assert m is not None
        return _yaml.safe_load(m.group(1))

    # Comparar con un build de FM hecho directamente desde los valores del JSON
    # (no con el ``_sample_dict`` crudo, que incluye keys extra como ``chapter``).
    fm_direct = build_front_matter_fields(
        title=json_payload["title"],
        book_slug=json_payload["book_slug"],
        chapter_slug=json_payload["chapter_slug"],
        pages=json_payload["pages"],
        source_file=json_payload["source_file"],
        source_sha256=json_payload["source_sha256"],
        converted_at=json_payload["generated_at"],
        capmd_version=json_payload["capmd_version"],
        cleaners_applied=tuple(json_payload["cleaners_applied"]),
        markitdown_version=json_payload["markitdown_version"],
    )
    rendered_direct = render_front_matter(fm_direct)
    parsed_json_block = _parse_block(rendered_json)
    parsed_direct = _parse_block(rendered_direct)
    assert parsed_json_block == parsed_direct


def test_front_matter_fields_from_capmd_json_rejects_wrong_version() -> None:
    payload = _sample_dict()
    payload["schema_version"] = 1
    with pytest.raises(ValueError, match="schema_version"):
        front_matter_fields_from_capmd_json(payload)


def test_front_matter_fields_from_capmd_json_missing_key() -> None:
    payload = _sample_dict()
    del payload["title"]
    with pytest.raises(KeyError, match="title"):
        front_matter_fields_from_capmd_json(payload)


def test_front_matter_fields_from_capmd_json_handles_null_fields() -> None:
    """Stdin: source_file/sha256/pages null."""
    payload = _sample_dict()
    payload["source_file"] = None
    payload["source_sha256"] = None
    payload["pages"] = None
    payload["book_slug"] = "stdin"
    payload["chapter_slug"] = "full"
    fm = front_matter_fields_from_capmd_json(payload)
    assert fm["source_file"] is None
    assert fm["source_sha256"] is None
    assert fm["pages"] is None
    assert fm["book"] == "stdin"
    assert fm["chapter"] == "full"


def test_regenerated_fm_renders_and_prepends() -> None:
    """El FM regenerado se puede prepender como cualquier otro."""
    payload = _sample_dict()
    fm = front_matter_fields_from_capmd_json(payload)
    body = "# Title\n\nbody text"
    full = prepend_front_matter(body, fm)
    assert full.startswith("---\n")
    assert "title: Ownership" in full
