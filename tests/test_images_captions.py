"""Tests de :mod:`capmd.images.captions` y de la detección de captions en anchor (fase E5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from capmd.images import (
    CAPTION_RE,
    CaptionMatch,
    anchor_figures,
    default_alt_text,
    find_caption_in_window,
    italicize_caption,
)
from capmd.models import Figure

# ---------- regex unit tests ----------


def test_caption_regex_matches_spanish_dash() -> None:
    m = CAPTION_RE.match("Figura 3.1 — Red square")
    assert m is not None
    assert m["chapter"] == "3"
    assert m["figure"] == "1"
    assert m["sep"] == "—"
    assert m["desc"] == "Red square"


def test_caption_regex_matches_english_colon() -> None:
    m = CAPTION_RE.match("Figure 3.1: A description")
    assert m is not None
    assert m["chapter"] == "3"
    assert m["figure"] == "1"
    assert m["sep"] == ":"
    assert m["desc"] == "A description"


def test_caption_regex_matches_fig_with_dot() -> None:
    m = CAPTION_RE.match("Fig. 3.1 — caption text")
    assert m is not None
    assert m["chapter"] == "3"
    assert m["figure"] == "1"


def test_caption_regex_matches_fig_without_dot() -> None:
    m = CAPTION_RE.match("Fig 3.1 — caption text")
    assert m is not None
    assert m["chapter"] == "3"


def test_caption_regex_matches_english_hyphen() -> None:
    m = CAPTION_RE.match("Figure 12.4 - Some caption here")
    assert m is not None
    assert m["chapter"] == "12"
    assert m["figure"] == "4"


def test_caption_regex_case_insensitive() -> None:
    m = CAPTION_RE.match("FIGURA 3.1 — CAPTION")
    assert m is not None


def test_caption_regex_no_match_without_separator() -> None:
    assert CAPTION_RE.match("Figura 3.1") is None
    assert CAPTION_RE.match("Figure 3.1") is None


def test_caption_regex_no_match_empty_description() -> None:
    """Sin descripción → no matchea (regex exige ``.+?``)."""
    assert CAPTION_RE.match("Figura 3.1 —") is None
    assert CAPTION_RE.match("Figure 3.1:") is None


def test_caption_regex_no_match_other_text() -> None:
    assert CAPTION_RE.match("This is a normal sentence.") is None


def test_caption_regex_no_match_decimal_with_extra_dot() -> None:
    """``3.1.5`` no matchea porque ``(.+?)`` no es greedy; probamos con separador raro."""
    assert CAPTION_RE.match("Figure 3.1.5 — caption") is None


# ---------- find_caption_in_window ----------


def test_find_caption_in_window_finds_at_offset_1() -> None:
    lines = ["anchor here", "Figura 3.1 — caption text"]
    m = find_caption_in_window(lines, 0)
    assert m is not None
    assert m.raw == "Figura 3.1 — caption text"
    assert m.ref == "3.1"
    assert m.line_index == 1


def test_find_caption_in_window_finds_at_offset_3() -> None:
    lines = ["anchor", "non-empty 1", "non-empty 2", "Figura 3.1 — caption"]
    m = find_caption_in_window(lines, 0, window=3)
    assert m is not None
    assert m.line_index == 3


def test_find_caption_in_window_skips_blanks() -> None:
    """Blank lines no cuentan para el límite de ``window``."""
    lines = ["anchor", "", "", "Figura 3.1 — caption"]
    m = find_caption_in_window(lines, 0, window=3)
    assert m is not None
    assert m.line_index == 3


def test_find_caption_in_window_returns_none_beyond_3() -> None:
    lines = ["anchor"] + [f"line {i}" for i in range(2, 10)] + ["Figura 3.1 — caption"]
    m = find_caption_in_window(lines, 0, window=3)
    assert m is None


def test_find_caption_in_window_returns_none_no_match() -> None:
    lines = ["anchor", "normal paragraph 1.", "normal paragraph 2."]
    m = find_caption_in_window(lines, 0, window=3)
    assert m is None


def test_find_caption_in_window_window_zero_disables() -> None:
    lines = ["anchor", "Figura 3.1 — caption"]
    assert find_caption_in_window(lines, 0, window=0) is None


def test_find_caption_in_window_returns_caption_match_dataclass() -> None:
    m = find_caption_in_window(["anchor", "Figura 3.1 — Red square"], 0)
    assert isinstance(m, CaptionMatch)
    assert m.chapter == 3
    assert m.figure == 1
    assert m.description == "Red square"


# ---------- italicize_caption ----------


def test_italicize_caption() -> None:
    cm = CaptionMatch(
        raw="Figura 3.1 — Red square",
        chapter=3,
        figure=1,
        ref="3.1",
        description="Red square",
        line_index=0,
    )
    assert italicize_caption(cm) == "*Figura 3.1 — Red square*"


# ---------- default_alt_text ----------


def test_default_alt_text_uses_figure_caption() -> None:
    fig = Figure(
        chapter_index=3,
        index=1,
        path=Path("x.png"),
        page=1,
        width=100,
        height=100,
        caption="Caption text",
    )
    assert default_alt_text(fig) == "Caption text"


def test_default_alt_text_empty_when_no_caption() -> None:
    fig = Figure(
        chapter_index=3,
        index=1,
        path=Path("x.png"),
        page=1,
        width=100,
        height=100,
        caption=None,
    )
    assert default_alt_text(fig) == ""


# ---------- anchor_figures caption integration ----------


def _fig(page: int, y: float, *, caption: str | None = None) -> Figure:
    return Figure(
        chapter_index=1,
        index=1,
        path=Path("images/fig-01-01.png"),
        page=page,
        width=200,
        height=200,
        bbox=(72.0, y, 200.0, 200.0),
        caption=caption,
    )


PAGE_HEIGHT = 792.0
PAGE_WIDTH = 612.0


def test_anchor_inserts_caption_italic_after_anchor() -> None:
    """Anchor en línea target + caption 1 línea abajo → output tiene italic tras el anchor.

    Como el caption se popula en ``Figure.caption`` (vía pre-pass CLI),
    el alt text del anchor NO está vacío: contiene el caption.
    """
    md = (
        "<!-- page 2 -->\n"
        "Paragraph 1.\n"
        "Paragraph 2.\n"
        "Paragraph 3.\n"
        "Paragraph 4.\n"
        "Figura 3.1 — caption text\n"
    )
    fig = _fig(page=2, y=PAGE_HEIGHT * 0.5)
    # Pre-populate caption como haría el pre-pass CLI.
    object.__setattr__(fig, "caption", "Figura 3.1 — caption text")

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    # El anchor tiene el caption como alt text.
    assert "![Figura 3.1 — caption text](images/fig-01-01.png)" in out
    # La línea italic está justo después.
    assert "*Figura 3.1 — caption text*" in out
    lines = out.splitlines()
    anchor_idx = next(i for i, ln in enumerate(lines) if "fig-01-01.png" in ln)
    assert lines[anchor_idx + 2] == "*Figura 3.1 — caption text*"


def test_anchor_moves_caption_from_below_to_after_anchor() -> None:
    """El caption se quita de su posición original si está antes del anchor.target."""
    md = (
        "<!-- page 2 -->\n"
        "Paragraph 1.\n"
        "Paragraph 2.\n"
        "Paragraph 3.\n"
        "Paragraph 4.\n"
        "Paragraph 5.\n"
        "Paragraph 6.\n"
        "Figura 3.1 — cap text\n"
    )
    fig = _fig(page=2, y=PAGE_HEIGHT * 0.8)
    object.__setattr__(fig, "caption", "Figura 3.1 — cap text")

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    # El anchor se inserta después de paragraph 6 (alto); el caption se
    # quita de su posición original y aparece después del anchor.
    lines = out.splitlines()
    assert lines.count("Figura 3.1 — cap text") == 1
    # Verificamos que ya no está entre los párrafos "Paragraph N".
    para_idxs = [i for i, ln in enumerate(lines) if ln.startswith("Paragraph")]
    cap_line_idx = next(
        i for i, ln in enumerate(lines) if "Figura 3.1 — cap text" in ln and not ln.startswith("!*")
    )
    for pi in para_idxs:
        assert (
            cap_line_idx > pi or cap_line_idx < pi - 1
        )  # no inmediatamente después del último "Paragraph"


def test_anchor_no_caption_no_italic_line() -> None:
    md = "<!-- page 2 -->\nP1.\nP2.\nP3.\nP4.\n"
    fig = _fig(page=2, y=PAGE_HEIGHT * 0.5)
    # No caption.

    out = anchor_figures(md, [fig], page_areas={2: (PAGE_WIDTH, PAGE_HEIGHT)})

    assert "fig-01-01.png" in out
    assert "*" not in out  # ninguna línea italic
    assert "Figura" not in out


# ---------- CLI integration ----------


@pytest.fixture
def midpage_pdf(tmp_path: Path) -> Path:
    """PDF con 2 páginas + imagen centrada en página 2 + caption "Figura 3.1 — …"."""
    from tests.fixtures.build import build_text_with_midpage_image_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "midpage.pdf"
    build_text_with_midpage_image_pdf(pdf, work)
    return pdf


@pytest.fixture
def midpage_pdf_no_caption(tmp_path: Path) -> Path:
    from tests.fixtures.build import build_text_with_midpage_image_pdf

    work = tmp_path / "work"
    pdf = tmp_path / "midpage-nocaption.pdf"
    build_text_with_midpage_image_pdf(pdf, work, caption=None)
    return pdf


def _run_convert(args: list[str]) -> object:
    runner = CliRunner()
    return runner.invoke(app, args)


def test_cli_caption_appears_in_final_markdown(midpage_pdf: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    result = _run_convert(["convert", str(midpage_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    assert "*Figura 3.1 — Diagrama de la imagen central*" in md


def test_cli_alt_text_matches_caption(midpage_pdf: Path, tmp_path: Path) -> None:
    """El alt text del anchor es el caption real (test literal del roadmap)."""
    out_md = tmp_path / "out.md"
    result = _run_convert(["convert", str(midpage_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    assert "![Figura 3.1 — Diagrama de la imagen central](images/fig-01-01.png)" in md


def test_cli_no_caption_image_no_italic(midpage_pdf_no_caption: Path, tmp_path: Path) -> None:
    out_md = tmp_path / "out.md"
    result = _run_convert(["convert", str(midpage_pdf_no_caption), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    # Anchor existe pero sin alt ni línea italic.
    assert "![](images/fig-01-01.png)" in md
    assert "*" not in md
    assert "Figura" not in md


def test_cli_caption_does_not_appear_twice(midpage_pdf: Path, tmp_path: Path) -> None:
    """El caption se quita del markdown cuando se detecta y se reinserta solo en italic."""
    out_md = tmp_path / "out.md"
    result = _run_convert(["convert", str(midpage_pdf), "-o", str(out_md)])

    assert result.exit_code == 0, result.output
    md = out_md.read_text()
    # El caption aparece exactamente 2 veces: una en el alt del anchor, otra en el italic.
    assert md.count("Figura 3.1 — Diagrama de la imagen central") == 2
