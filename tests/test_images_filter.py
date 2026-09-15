"""Tests de :mod:`capmd.images.filter` y del pipeline E1+E2 (fase E2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from capmd.cli import app
from capmd.images import (
    ImageCandidate,
    extract_figures,
)
from capmd.images.filter import (
    FilterDecision,
    FilterRules,
    filter_candidates,
)

# ---------- helpers ----------


def _rgb(w: int, h: int, color: tuple[int, int, int]) -> Image.Image:
    """Crea una imagen PIL sólida (RGB) de tamaño w*h con el color dado."""
    return Image.new("RGB", (w, h), color)


def _cand(
    image: Image.Image, page: int = 1, bbox: tuple[float, float, float, float] | None = None
) -> ImageCandidate:
    return ImageCandidate(image=image, page=page, bbox=bbox)


def _page_areas(
    pages: list[int], width: float = 612.0, height: float = 792.0
) -> dict[int, tuple[float, float]]:
    return {p: (width, height) for p in pages}


# ---------- tests unitarios del filtro ----------


def test_filter_too_small_drops_tiny() -> None:
    tiny = _cand(_rgb(50, 50, (10, 10, 10)), page=1)
    big = _cand(_rgb(200, 200, (10, 10, 10)), page=1)

    report = filter_candidates([tiny, big], _page_areas([1]), FilterRules(min_size=(64, 64)))

    assert report.total_in == 2
    assert report.total_kept == 1
    assert big in report.kept
    assert tiny in report.dropped[FilterDecision.TOO_SMALL]


def test_filter_background_drops_full_page() -> None:
    bg = _cand(
        _rgb(1000, 1000, (255, 255, 255)),
        page=1,
        bbox=(0.0, 0.0, 612.0, 792.0),
    )
    real = _cand(_rgb(200, 200, (10, 10, 10)), page=1, bbox=(100.0, 100.0, 200.0, 200.0))

    report = filter_candidates([bg, real], _page_areas([1]), FilterRules(background_coverage=0.85))

    assert report.total_kept == 1
    assert real in report.kept
    assert bg in report.dropped[FilterDecision.BACKGROUND]


def test_filter_logo_repeated_keeps_first() -> None:
    logo = _rgb(80, 80, (40, 40, 40))
    cands = [_cand(logo.copy(), page=p) for p in range(1, 5)]

    report = filter_candidates(cands, _page_areas([1, 2, 3, 4]), FilterRules(repeat_threshold=0.8))

    assert report.total_in == 4
    assert report.total_kept == 1
    assert report.dropped[FilterDecision.LOGO_REPEATED] is not None
    assert len(report.dropped[FilterDecision.LOGO_REPEATED]) == 3
    assert cands[0] in report.kept


def test_filter_logo_threshold_not_reached_keeps_all() -> None:
    """Si cada candidato tiene un hash distinto, no se aplica la dedup por repetición."""
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    cands = [_cand(_rgb(150, 150, c), page=p) for p, c in zip([1, 2, 3, 4], colors, strict=True)]

    report = filter_candidates(cands, _page_areas([1, 2, 3, 4]), FilterRules(repeat_threshold=0.8))

    assert report.total_in == 4
    assert report.total_kept == 4
    assert report.dropped.get(FilterDecision.LOGO_REPEATED, ()) == ()


def test_filter_mixed_decisions_correctly() -> None:
    pages = [1, 2]
    areas = _page_areas(pages)

    too_small = _cand(_rgb(30, 30, (1, 1, 1)), page=1)
    background = _cand(_rgb(800, 800, (5, 5, 5)), page=1, bbox=(0.0, 0.0, 612.0, 792.0))
    repeated_logo = _cand(_rgb(80, 80, (40, 40, 40)), page=1)
    repeated_logo_2 = _cand(_rgb(80, 80, (40, 40, 40)), page=2)
    valid_a = _cand(_rgb(200, 200, (200, 50, 50)), page=1, bbox=(100.0, 100.0, 200.0, 200.0))
    valid_b = _cand(_rgb(200, 200, (50, 80, 220)), page=2, bbox=(100.0, 100.0, 200.0, 200.0))

    cands = [too_small, background, repeated_logo, repeated_logo_2, valid_a, valid_b]
    report = filter_candidates(cands, areas)

    assert report.total_in == 6
    assert report.total_kept == 3
    assert valid_a in report.kept
    assert valid_b in report.kept
    assert repeated_logo in report.kept  # primera aparición del logo conservada
    assert repeated_logo_2 in report.dropped.get(FilterDecision.LOGO_REPEATED, ())
    assert too_small in report.dropped[FilterDecision.TOO_SMALL]
    assert background in report.dropped[FilterDecision.BACKGROUND]


def test_filter_rules_validation() -> None:
    with pytest.raises(ValueError, match="min_size"):
        FilterRules(min_size=(0, 64))
    with pytest.raises(ValueError, match="repeat_threshold"):
        FilterRules(repeat_threshold=1.5)
    with pytest.raises(ValueError, match="background_coverage"):
        FilterRules(background_coverage=0.0)


def test_filter_summary() -> None:
    tiny = _cand(_rgb(10, 10, (1, 1, 1)), page=1)
    big = _cand(_rgb(100, 100, (1, 1, 1)), page=1)
    report = filter_candidates([tiny, big], _page_areas([1]))
    s = report.summary()
    assert "1/2" in s
    assert "too_small" in s


def test_filter_no_bbox_no_background_decision() -> None:
    """Si el bbox es None, BACKGROUND no se evalúa; la imagen puede pasar a KEPT."""
    img = _rgb(200, 200, (10, 10, 10))
    cands = [_cand(img, page=1, bbox=None)]
    report = filter_candidates(cands, _page_areas([1]))
    assert report.total_kept == 1
    assert report.dropped.get(FilterDecision.BACKGROUND, ()) == ()


# ---------- tests de integración con fixtures ----------


@pytest.fixture
def two_images_pdf(tmp_path: Path) -> Path:
    from tests.fixtures.build import build_two_images_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "two_images.pdf"
    build_two_images_pdf(pdf, work)
    return pdf


@pytest.fixture
def logo_repeated_pdf(tmp_path: Path) -> Path:
    from tests.fixtures.build import build_logo_repeated_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "logo.pdf"
    build_logo_repeated_pdf(pdf, work, n_pages=4)
    return pdf


def test_extract_figures_filters_logo_fixture(logo_repeated_pdf: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = extract_figures(logo_repeated_pdf, [1, 2, 3, 4], out_dir)

    pages = {fig.page for fig in result.figures}
    assert len(result.figures) == 2
    assert pages == {2, 4}


def test_extract_figures_backwards_compat_two_images(two_images_pdf: Path, tmp_path: Path) -> None:
    """El fixture de E1 sigue produciendo 2 figuras con los filtros por default."""
    out_dir = tmp_path / "out"
    result = extract_figures(two_images_pdf, [1], out_dir)

    assert len(result.figures) == 2


# ---------- tests de CLI ----------


def _run_convert(args: list[str]) -> object:
    runner = CliRunner()
    return runner.invoke(app, args)


def test_cli_filter_skips_logo_default(logo_repeated_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    result = _run_convert(["convert", str(logo_repeated_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    assert images_dir.is_dir()
    names = sorted(p.name for p in images_dir.glob("*.png"))
    assert names == ["fig-01-01.png", "fig-01-02.png"]


def test_cli_filter_repeat_threshold_flag(logo_repeated_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    # Con threshold 0.3, el logo (4/4 = 100% >= 30%) se descarta;
    # las 2 figuras reales (páginas 2 y 4) se conservan.
    result = _run_convert(
        [
            "convert",
            str(logo_repeated_pdf),
            "-o",
            str(out_md),
            "--filter-repeat-threshold",
            "0.3",
        ]
    )

    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in images_dir.glob("*.png"))
    assert names == ["fig-01-01.png", "fig-01-02.png"]


def test_cli_filter_min_size_too_strict_drops_everything(
    logo_repeated_pdf: Path, tmp_path: Path
) -> None:
    """Si subimos el mínimo a 500x500, hasta las figuras reales caen por TOO_SMALL."""
    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"

    result = _run_convert(
        [
            "convert",
            str(logo_repeated_pdf),
            "-o",
            str(out_md),
            "--filter-min-size",
            "500x500",
        ]
    )

    assert result.exit_code == 0, result.output
    assert not list(images_dir.glob("*.png"))


# ---------- tests de TOML config ----------


def test_toml_override_loads_from_project_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "capmd.toml").write_text("[images]\nrepeat_threshold = 0.5\n", encoding="utf-8")
    from capmd.config import load_image_filter_overrides

    overrides = load_image_filter_overrides()
    assert overrides.get("repeat_threshold") == 0.5


def test_toml_override_project_overrides_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    global_toml = Path.home() / ".config" / "capmd" / "config.toml"
    original = global_toml.read_bytes() if global_toml.exists() else None
    global_toml.parent.mkdir(parents=True, exist_ok=True)
    try:
        global_toml.write_text("[images]\nrepeat_threshold = 0.3\n", encoding="utf-8")
        (tmp_path / "capmd.toml").write_text("[images]\nrepeat_threshold = 0.7\n", encoding="utf-8")
        from capmd.config import load_image_filter_overrides

        overrides = load_image_filter_overrides()
        assert overrides.get("repeat_threshold") == 0.7
    finally:
        if original is not None:
            global_toml.write_bytes(original)
        else:
            global_toml.unlink(missing_ok=True)


def test_toml_override_missing_file_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    from capmd.config import load_image_filter_overrides

    overrides = load_image_filter_overrides()
    assert overrides == {}


def test_toml_override_malformed_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "capmd.toml").write_text("this is not [valid toml", encoding="utf-8")
    from capmd.config import load_image_filter_overrides

    overrides = load_image_filter_overrides()
    assert overrides == {}


def test_toml_override_unknown_keys_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "capmd.toml").write_text(
        "[images]\nfoobar = 1\nrepeat_threshold = 0.5\n", encoding="utf-8"
    )
    from capmd.config import load_image_filter_overrides

    overrides = load_image_filter_overrides()
    assert "foobar" not in overrides
    assert overrides.get("repeat_threshold") == 0.5


def test_cli_with_toml_override_changes_behavior(
    logo_repeated_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # min_size=10x10 deja pasar el logo (50x50). El repeat_threshold=0.5 dispara
    # el dedup: el logo aparece en 4/4=100% -> se conserva la primera aparición.
    # Resultado: 1 logo + 2 figuras reales = 3 archivos en images/.
    (tmp_path / "capmd.toml").write_text(
        '[images]\nmin_size = "10x10"\nrepeat_threshold = 0.5\n',
        encoding="utf-8",
    )

    out_md = tmp_path / "out.md"
    images_dir = tmp_path / "images"
    result = _run_convert(["convert", str(logo_repeated_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in images_dir.glob("*.png"))
    assert names == ["fig-01-01.png", "fig-01-02.png", "fig-01-03.png"]
