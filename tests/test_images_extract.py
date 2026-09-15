"""Tests de :mod:`capmd.images.extract` (fase E1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from capmd.cli import app
from capmd.images import (
    SUPPORTED_IMAGE_FORMATS,
    ExtractOptions,
    extract_figures,
)


@pytest.fixture
def two_images_pdf(tmp_path: Path) -> Path:
    """PDF de 1 página con exactamente 2 imágenes embebidas de 200x200."""
    from tests.fixtures.build import build_two_images_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "two_images.pdf"
    build_two_images_pdf(pdf, work)
    return pdf


def test_extract_two_images_produces_two_files(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(two_images_pdf, [1], out_dir)
    figures = result.figures

    assert len(figures) == 2
    paths = sorted(out_dir.glob("*.png"))
    assert len(paths) == 2
    assert paths[0].name == "fig-01-01.png"
    assert paths[1].name == "fig-01-02.png"


def test_extract_dimensions_match(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(two_images_pdf, [1], out_dir)
    figures = result.figures

    assert len(figures) == 2
    for fig in figures:
        assert fig.width == 200
        assert fig.height == 200
        with Image.open(fig.path) as im:
            assert im.width == 200
            assert im.height == 200


def test_extract_webp_format(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(
        two_images_pdf,
        [1],
        out_dir,
        options=ExtractOptions(image_format="webp"),
    )
    figures = result.figures

    assert len(figures) == 2
    for fig in figures:
        assert fig.path.suffix == ".webp"
        with Image.open(fig.path) as im:
            assert im.format == "WEBP"


def test_extract_max_width_downsamples(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(
        two_images_pdf,
        [1],
        out_dir,
        options=ExtractOptions(max_width=100),
    )
    figures = result.figures

    assert len(figures) == 2
    for fig in figures:
        assert fig.width == 100
        assert fig.height == 100
        with Image.open(fig.path) as im:
            assert im.width == 100
            assert im.height == 100


def test_extract_max_width_unchanged_when_smaller(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(
        two_images_pdf,
        [1],
        out_dir,
        options=ExtractOptions(max_width=400),
    )
    figures = result.figures

    assert len(figures) == 2
    for fig in figures:
        assert fig.width == 200
        assert fig.height == 200


def test_extract_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="formato no soportado"):
        ExtractOptions(image_format="gif")


def test_extract_empty_pages_returns_empty(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(two_images_pdf, [], out_dir)
    assert result.figures == []


def test_extract_deterministic_filenames(two_images_pdf: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    figures_a = extract_figures(two_images_pdf, [1], out_a).figures
    figures_b = extract_figures(two_images_pdf, [1], out_b).figures

    names_a = [fig.path.name for fig in figures_a]
    names_b = [fig.path.name for fig in figures_b]
    assert names_a == names_b
    assert names_a == ["fig-01-01.png", "fig-01-02.png"]


def test_extract_non_pdf_raises(tmp_path: Path) -> None:
    txt = tmp_path / "not_a_pdf.txt"
    txt.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="solo se extraen imágenes de PDF"):
        extract_figures(txt, [1], tmp_path / "out")


def _run_convert(args: list[str]) -> object:
    runner = CliRunner()
    return runner.invoke(app, args)


def test_cli_default_creates_images_for_pdf(two_images_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    result = _run_convert(["convert", str(two_images_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    assert images_dir.is_dir(), "capmd debe crear images/ junto al -o"
    images = sorted(p.name for p in images_dir.glob("*.png"))
    assert images == ["fig-01-01.png", "fig-01-02.png"]


def test_cli_image_format_flag_propagates(two_images_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    result = _run_convert(
        [
            "convert",
            str(two_images_pdf),
            "-o",
            str(out_md),
            "--image-format",
            "webp",
        ]
    )

    assert result.exit_code == 0, result.output
    images = sorted(p.name for p in images_dir.glob("*.webp"))
    assert images == ["fig-01-01.webp", "fig-01-02.webp"]


def test_cli_image_max_width_propagates(two_images_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    result = _run_convert(
        [
            "convert",
            str(two_images_pdf),
            "-o",
            str(out_md),
            "--image-max-width",
            "100",
        ]
    )

    assert result.exit_code == 0, result.output
    for img_path in images_dir.glob("*.png"):
        with Image.open(img_path) as im:
            assert im.width == 100
            assert im.height == 100


def test_supported_image_formats_constant() -> None:
    assert frozenset({"png", "webp"}) == SUPPORTED_IMAGE_FORMATS
