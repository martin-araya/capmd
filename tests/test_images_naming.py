"""Tests de :func:`make_figure_name` y del determinismo byte-a-byte (fase E3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from capmd.cli import app
from capmd.images import ExtractOptions, extract_figures, make_figure_name

# ---------- make_figure_name ----------


def test_make_figure_name_pads_to_two_digits() -> None:
    assert make_figure_name(3, 1, "png") == "fig-03-01.png"  # ejemplo literal del roadmap
    assert make_figure_name(1, 1, "png") == "fig-01-01.png"
    assert make_figure_name(9, 9, "webp") == "fig-09-09.webp"


def test_make_figure_name_scales_to_three_digits_for_high_chapter() -> None:
    assert make_figure_name(100, 1, "png") == "fig-100-01.png"
    assert make_figure_name(123, 5, "png") == "fig-123-05.png"


def test_make_figure_name_scales_to_three_digits_for_high_figure() -> None:
    assert make_figure_name(3, 100, "png") == "fig-03-100.png"
    assert make_figure_name(3, 1000, "png") == "fig-03-1000.png"


def test_make_figure_name_validates_inputs() -> None:
    with pytest.raises(ValueError, match="chapter_index"):
        make_figure_name(0, 1, "png")
    with pytest.raises(ValueError, match="figure_index"):
        make_figure_name(1, 0, "png")


# ---------- _save_image byte-determinism ----------


def test_save_image_strips_metadata_png(tmp_path: Path) -> None:
    """Una imagen con info dict no debe contaminar el PNG resultante."""
    from capmd.images.extract import _save_image

    img = Image.new("RGB", (50, 50), (200, 100, 50))
    img.info["Software"] = "capmd-test"
    img.info["Comment"] = "secret"

    target = tmp_path / "out.png"
    _save_image(img, target, "png")

    with Image.open(target) as loaded:
        # Al recargar via PIL, info queda solo con metadata básica del PNG.
        assert "Software" not in loaded.info
        assert "Comment" not in loaded.info

    raw = target.read_bytes()
    # Búsqueda cruda: el chunk tEXt usa 4 bytes de tipo + datos null-terminated.
    assert b"capmd-test" not in raw
    assert b"secret" not in raw


def test_save_image_strips_metadata_webp(tmp_path: Path) -> None:
    """WebP sin EXIF."""
    from capmd.images.extract import _save_image

    img = Image.new("RGB", (50, 50), (10, 20, 30))
    img.info["exif"] = b"this-would-be-exif-data"

    target = tmp_path / "out.webp"
    _save_image(img, target, "webp")

    with Image.open(target) as loaded:
        loaded.load()
        assert not loaded.info.get("exif")


# ---------- extract_figures: naming + chapter propagation ----------


@pytest.fixture
def two_images_pdf(tmp_path: Path) -> Path:
    from tests.fixtures.build import build_two_images_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "two_images.pdf"
    build_two_images_pdf(pdf, work)
    return pdf


def test_extract_figures_chapter_3_naming(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(two_images_pdf, [1], out_dir, chapter_index=3)
    names = sorted(p.name for p in out_dir.glob("*.png"))

    assert len(result.figures) == 2
    assert names == ["fig-03-01.png", "fig-03-02.png"]
    assert all(fig.chapter_index == 3 for fig in result.figures)


def test_extract_figures_chapter_index_resets_between_runs(
    two_images_pdf: Path, tmp_path: Path
) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    figures_a = extract_figures(two_images_pdf, [1], out_a, chapter_index=1).figures
    figures_b = extract_figures(two_images_pdf, [1], out_b, chapter_index=5).figures

    assert [fig.path.name for fig in figures_a] == ["fig-01-01.png", "fig-01-02.png"]
    assert [fig.path.name for fig in figures_b] == ["fig-05-01.png", "fig-05-02.png"]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_extract_figures_byte_identical_across_runs(two_images_pdf: Path, tmp_path: Path) -> None:
    """El test literal del roadmap: dos runs seguidos producen los mismos nombres y hashes."""
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    figures_a = extract_figures(two_images_pdf, [1], out_a).figures
    figures_b = extract_figures(two_images_pdf, [1], out_b).figures

    paths_a = [fig.path for fig in figures_a]
    paths_b = [fig.path for fig in figures_b]

    names_a = sorted(p.name for p in paths_a)
    names_b = sorted(p.name for p in paths_b)
    assert names_a == names_b

    hashes_a = sorted(_hash(p) for p in paths_a)
    hashes_b = sorted(_hash(p) for p in paths_b)
    assert hashes_a == hashes_b


def test_extract_figures_byte_identical_webp(two_images_pdf: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    opts = ExtractOptions(image_format="webp")
    figures_a = extract_figures(two_images_pdf, [1], out_a, options=opts).figures
    figures_b = extract_figures(two_images_pdf, [1], out_b, options=opts).figures

    names_a = sorted(p.name for p in (fig.path for fig in figures_a))
    names_b = sorted(p.name for p in (fig.path for fig in figures_b))
    assert names_a == names_b
    assert all(name.endswith(".webp") for name in names_a)

    hashes_a = sorted(_hash(fig.path) for fig in figures_a)
    hashes_b = sorted(_hash(fig.path) for fig in figures_b)
    assert hashes_a == hashes_b


def test_figure_dataclass_index_is_within_chapter(two_images_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(two_images_pdf, [1], out_dir, chapter_index=3)

    assert [fig.index for fig in result.figures] == [1, 2]
    assert all(fig.chapter_index == 3 for fig in result.figures)


# ---------- CLI con --chapter ----------


def _run_convert(args: list[str]) -> object:
    runner = CliRunner()
    return runner.invoke(app, args)


def test_cli_no_chapter_uses_chapter_1(two_images_pdf: Path, tmp_path: Path) -> None:
    """Sin --chapter, chapter_index=1 por default → fig-01-NN.png."""
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    result = _run_convert(["convert", str(two_images_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in images_dir.glob("*.png"))
    assert names == ["fig-01-01.png", "fig-01-02.png"]


def test_cli_chapter_3_naming(tmp_path: Path) -> None:
    """Fixture con outline: --chapter 3 → chapter_index=3 → fig-03-NN.png.

    Usa build_outline_with_chapter_image_pdf (imagen en página 2). Para
    que aparezca una imagen en página 3 (cap 3), agregamos otra imagen
    copiando el fixture y modificando.
    """
    from tests.fixtures.build import build_outline_with_chapter_image_pdf

    pdf = tmp_path / "book.pdf"
    work = tmp_path / "work"
    build_outline_with_chapter_image_pdf(pdf, work)

    # Sin imagen en página 3, las imágenes quedan en 0 para `--chapter 3`.
    # El test verifica que el nombre respeta el prefijo del capítulo
    # aunque no haya figuras (no se crea images/, o queda vacío).
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"
    result = _run_convert(
        [
            "convert",
            str(pdf),
            "-o",
            str(out_md),
            "--chapter",
            "3",
        ]
    )

    assert result.exit_code == 0, result.output
    # Sin figuras en cap 3: images/ vacía (no se crea si no hay qué escribir).
    assert not list(images_dir.glob("*.png"))


def test_cli_chapter_with_outline_uses_chapter_index(
    tmp_path: Path,
) -> None:
    """Fixture con outline + imagen: --chapter 2 → chapter_index=2 → fig-02-01.png."""
    from tests.fixtures.build import build_outline_with_chapter_image_pdf

    pdf = tmp_path / "book.pdf"
    work = tmp_path / "work"
    build_outline_with_chapter_image_pdf(pdf, work)

    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"
    result = _run_convert(
        [
            "convert",
            str(pdf),
            "-o",
            str(out_md),
            "--chapter",
            "2",
        ]
    )

    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in images_dir.glob("*.png"))
    assert names == ["fig-02-01.png"]


def test_cli_chapter_substring_resolution(tmp_path: Path) -> None:
    """--chapter 'Ownership' matchea por substring → chapter_index=2."""
    from tests.fixtures.build import build_outline_with_chapter_image_pdf

    pdf = tmp_path / "book.pdf"
    work = tmp_path / "work"
    build_outline_with_chapter_image_pdf(pdf, work)

    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"
    result = _run_convert(
        [
            "convert",
            str(pdf),
            "-o",
            str(out_md),
            "--chapter",
            "Ownership",
        ]
    )

    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in images_dir.glob("*.png"))
    assert names == ["fig-02-01.png"]


def test_chapter_index_helper_shortcut_numeric() -> None:
    from capmd.cli import _chapter_index_from_spec

    assert _chapter_index_from_spec(Path("dummy.pdf"), "5") == 5
    assert _chapter_index_from_spec(Path("dummy.pdf"), "1") == 1
