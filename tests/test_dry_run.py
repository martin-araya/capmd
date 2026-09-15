"""Tests unitarios de ``capmd.dryrun`` (F7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from capmd.dryrun import (
    DRY_RUN_SCHEMA_VERSION,
    DryRunPlan,
    build_dry_run_plan,
    render_plan_json,
    render_plan_text,
)
from capmd.models import Chapter, PageRange

# --- Helpers --------------------------------------------------------------


def _fake_report() -> dict:
    return {
        "report_schema_version": 1,
        "format": "json",
        "stats": {
            "cleaned_chars": 100,
            "cleaners": {"per_cleaner": {}, "total_changes": 0},
            "deletion_ratio": 0.0,
            "elapsed_seconds": 0.1,
            "figures": 0,
            "headings": {
                "h1": 1, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0, "total": 1,
            },
            "pages": 1,
            "raw_chars": 100,
            "source_format": "pdf",
            "words": 20,
        },
        "warnings": [],
    }


def _build_plan(
    *,
    requested_out_dir: Path | None = None,
    requested_output: Path | None = None,
    flat: bool = False,
    split: str | None = None,
    toc: bool = False,
    toc_depth: int = 3,
    final_markdown: str = "# Title\n\nbody\n",
    stdin: bool = False,
    source_path: Path | None = None,
    source_format: str = "pdf",
    pages: int | None = 1,
    resolved_chapter: Chapter | None = None,
    resolved_page_range: PageRange | None = None,
    page_offset: int = 0,
    report: dict | None = None,
) -> DryRunPlan:
    return build_dry_run_plan(
        requested_out_dir=requested_out_dir,
        requested_output=requested_output,
        flat=flat,
        split=split,
        toc=toc,
        toc_depth=toc_depth,
        no_images=False,
        no_anchor=False,
        no_clean=False,
        only_clean=None,
        skip_clean=None,
        image_format="png",
        source=str(source_path) if source_path is not None and not stdin else "<stdin>",
        source_path=source_path,
        stdin=stdin,
        source_format=source_format,
        pages=pages,
        size_bytes=None,
        sha256=None,
        resolved_chapter=resolved_chapter,
        resolved_page_range=resolved_page_range,
        page_offset=page_offset,
        final_markdown=final_markdown,
        report=report or _fake_report(),
    )


# --- Tree mode -------------------------------------------------------------


def test_tree_kind_with_out_dir(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    out_dir = tmp_path / "out"
    plan = _build_plan(
        requested_out_dir=out_dir,
        source_path=pdf,
        source_format="pdf",
    )
    assert plan.output.kind == "tree"
    assert plan.output.requested == str(out_dir)
    # tree_files debe tener al menos 3 paths: el chapter.md, images/, capmd.json.
    assert any(p.endswith(".md") for p in plan.output.tree_files)
    assert any(p.endswith("/images/") for p in plan.output.tree_files)
    assert any(p.endswith("capmd.json") for p in plan.output.tree_files)


def test_tree_with_split_h2_includes_sections(tmp_path: Path) -> None:
    """Con --split h2 el plan lista los archivos de cada sección."""
    pdf = tmp_path / "book.pdf"
    out_dir = tmp_path / "out"
    md = "# Title\n\n## A\nbody a\n\n## B\nbody b\n"
    plan = _build_plan(
        requested_out_dir=out_dir,
        source_path=pdf,
        source_format="pdf",
        final_markdown=md,
        split="h2",
    )
    assert plan.output.kind == "tree"
    paths = plan.output.tree_files
    # Al menos las dos secciones + index.md.
    assert any(p.endswith("/sections/01-a.md") for p in paths), paths
    assert any(p.endswith("/sections/02-b.md") for p in paths), paths
    assert any(p.endswith("/sections/index.md") for p in paths), paths


def test_flat_kind(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    out_dir = tmp_path / "out"
    plan = _build_plan(
        requested_out_dir=out_dir,
        flat=True,
        source_path=pdf,
    )
    assert plan.output.kind == "flat"
    # Un solo archivo .md.
    assert len(plan.output.tree_files) == 1
    assert plan.output.tree_files[0].endswith(".md")


# --- single-file / stdout ------------------------------------------------


def test_single_file_kind(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    out_file = tmp_path / "single.md"
    plan = _build_plan(
        requested_out_dir=None,
        requested_output=out_file,
        source_path=pdf,
    )
    assert plan.output.kind == "single-file"
    assert plan.output.requested == str(out_file)
    assert plan.output.tree_files == (str(out_file),)


def test_stdout_kind_when_no_output_specified(tmp_path: Path) -> None:
    """Sin --out ni -o FILE: kind=stdout, tree_files=[], requested=None."""
    plan = _build_plan(
        stdin=True,
        requested_out_dir=None,
        requested_output=None,
    )
    assert plan.output.kind == "stdout"
    assert plan.output.requested is None
    assert plan.output.tree_files == ()


# --- Report embedding -----------------------------------------------------


def test_plan_embeds_report() -> None:
    plan = _build_plan()
    assert "report" in plan.as_dict()
    assert plan.report["stats"]["words"] == 20
    assert plan.report["warnings"] == []


def test_plan_embeds_warnings() -> None:
    fake_report = _fake_report()
    fake_report["warnings"] = [
        {"code": "x", "message": "y", "suggestion": "z"},
    ]
    plan = _build_plan(report=fake_report)
    assert len(plan.report["warnings"]) == 1
    assert plan.report["warnings"][0]["code"] == "x"


# --- Renderers ------------------------------------------------------------


def test_render_plan_json_parses() -> None:
    plan = _build_plan()
    parsed = json.loads(render_plan_json(plan))
    assert parsed["dry_run"] is True
    assert parsed["schema_version"] == DRY_RUN_SCHEMA_VERSION
    assert "input" in parsed
    assert "selection" in parsed
    assert "flags" in parsed
    assert "output" in parsed
    assert "report" in parsed


def test_render_plan_text_contains_key_info() -> None:
    plan = _build_plan()
    text = render_plan_text(plan)
    assert "capmd dry-run" in text
    assert "pdf" in text
    # Texto no parseable como JSON.
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)
