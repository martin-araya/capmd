"""Tests del cleaner kerning (FIX-8 / D9)."""

from __future__ import annotations

from pathlib import Path

from capmd.clean import (
    CleanContext,
    KerningCleaner,
    Pipeline,
    collapse_kerning,
)
from capmd.clean.pipeline import available_cleaner_names, default_pipeline
from capmd.models import SourceDoc


def _ctx(tmp_path: Path) -> CleanContext:
    return CleanContext(
        source=SourceDoc(
            path=tmp_path / "x.pdf",
            format="pdf",
            sha256="0" * 64,
            size_bytes=0,
        ),
        format="pdf",
    )


# --- pure function ---


def test_collapses_simple_uppercase_letters() -> None:
    assert collapse_kerning("C H A P T E R") == "CHAPTER"


def test_collapses_letters_then_digits_with_3_space_gap() -> None:
    """3+ espacios entre grupos no se colapsan; cada match es independiente."""
    assert collapse_kerning("C H A P T E R   1 1") == "CHAPTER   11"


def test_collapses_digits_only() -> None:
    assert collapse_kerning("1 0  2 0 4") == "10204"


def test_no_change_in_mixed_case_line() -> None:
    """False-positive guard: líneas mixtas (no 100% uppercase) no se tocan."""
    assert collapse_kerning("Section A B") == "Section A B"


def test_no_change_in_lowercase() -> None:
    assert collapse_kerning("c h a p t e r 1 1") == "c h a p t e r 1 1"


def test_no_change_with_punctuation() -> None:
    """Una coma, paréntesis u otro símbolo rompe la condición
    uppercase-only-line → no se toca."""
    assert (
        collapse_kerning("A B C, donde A=1, B=2")
        == "A B C, donde A=1, B=2"
    )


def test_empty_string() -> None:
    assert collapse_kerning("") == ""


def test_preserves_multiline_mixed() -> None:
    src = "Multi-line\nC H A P T E R\nSection A B\nFooter"
    assert collapse_kerning(src) == "Multi-line\nCHAPTER\nSection A B\nFooter"


# --- Cleaner class + pipeline ---


def test_kerning_cleaner_default_name() -> None:
    from capmd.clean.kerning import DEFAULT_NAME

    assert KerningCleaner().name == DEFAULT_NAME == "kerning"


def test_kerning_cleaner_pipeline_integration(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(KerningCleaner(),))
    src = "Intro\n\nC H A P T E R   1 1\n\nRequirements"
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert "C H A P T E R   1 1" not in text
    assert "CHAPTER" in text
    assert "11" in text
    assert stats[0].name == "kerning"
    # Dos matches colapsados: "C H A P T E R" + "1 1".
    assert stats[0].changes == 2


def test_kerning_preserves_code_fences(tmp_path: Path) -> None:
    """Code blocks ``` ... ``` no se tocan aunque contengan
    líneas uppercase-puras."""
    pipeline = Pipeline(cleaners=(KerningCleaner(),))
    src = (
        "Intro\n"
        "\n"
        "```bash\n"
        "A B C\n"
        "```\n"
        "\n"
        "Outro"
    )
    text, _stats = pipeline.run(src, _ctx(tmp_path))
    assert "A B C" in text  # fence preservado
    assert "ABC" not in text


def test_kerning_disabled(tmp_path: Path) -> None:
    src = "C H A P T E R 1 1"
    pipeline = Pipeline(cleaners=(KerningCleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_kerning_empty_input(tmp_path: Path) -> None:
    result = KerningCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


# --- Pipeline registration (FIX-8.3 / FIX-8.4) ---


def test_kerning_in_default_pipeline() -> None:
    """El cleaner debe estar registrado en ``default_pipeline()``."""
    names = [c.name for c in default_pipeline().cleaners]
    assert "kerning" in names
    # Orden: whitespace → kerning → …
    assert names.index("kerning") == names.index("whitespace") + 1


def test_kerning_in_available_cleaner_names() -> None:
    """Disponible para ``--only-clean kerning`` / ``--skip-clean kerning``."""
    assert "kerning" in available_cleaner_names()
