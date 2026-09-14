"""Tests del cleaner de cortes de párrafo (D14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    ParagraphJoinsCleaner,
    Pipeline,
    is_skip_line,
    join_paragraphs,
    should_join,
)
from capmd.clean.paragraph_joins import (
    DEFAULT_NAME,
    OPENING_BRACKETS,
    TERMINAL_PUNCTUATION,
)
from capmd.models import SourceDoc


def _make_source(tmp_path: Path) -> SourceDoc:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return SourceDoc(
        path=p,
        format="pdf",
        sha256="0" * 64,
        size_bytes=p.stat().st_size,
    )


def _ctx(tmp_path: Path) -> CleanContext:
    return CleanContext(source=_make_source(tmp_path), format="pdf")


# --- should_join ---


def test_should_join_no_terminal_lowercase_next() -> None:
    assert should_join("texto\n", "mundo\n")


def test_should_not_join_with_period() -> None:
    assert not should_join("texto.\n", "mundo\n")


def test_should_not_join_with_colon() -> None:
    assert not should_join("texto:\n", "mundo\n")


def test_should_not_join_with_semicolon() -> None:
    assert not should_join("texto;\n", "mundo\n")


def test_should_join_with_comma() -> None:
    assert should_join("texto,\n", "mundo\n")


def test_should_join_with_question() -> None:
    assert should_join("texto?\n", "mundo\n")


def test_should_join_with_exclamation() -> None:
    assert should_join("texto!\n", "mundo\n")


def test_should_join_opening_paren_next() -> None:
    assert should_join("texto (\n", "más texto\n")


def test_should_join_opening_bracket_next() -> None:
    assert should_join("texto [\n", "más\n")


def test_should_join_opening_quote_next() -> None:
    assert should_join('texto "\n', "más\n")


def test_should_not_join_uppercase_start() -> None:
    assert not should_join("texto\n", "Mundo\n")


def test_should_not_join_empty_next() -> None:
    assert not should_join("texto\n", "\n")


def test_should_join_prev_ends_with_opening_paren() -> None:
    assert should_join("texto (\n", "más)\n")


def test_should_not_join_prev_ends_with_terminal_but_next_opens() -> None:
    """Aunque curr abra bracket, prev terminal punctuation corta."""
    assert not should_join("texto.\n", "(más)\n")


# --- is_skip_line ---


@pytest.mark.parametrize(
    "line",
    [
        "# H1",
        "## H2",
        "###### H6",
        "- item",
        "* item",
        "+ item",
        "1. item",
        "2) item",
        "> quote",
        "```",
        "```python",
        "~~~",
        "  > indented blockquote",
        "  - indented list",
    ],
)
def test_is_skip_line_true(line: str) -> None:
    assert is_skip_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "texto normal",
        "Hello, world.",
        "normal with () inside",
        '"Hello," he said.',
        "abc",
        "",
        "   ",
    ],
)
def test_is_skip_line_false(line: str) -> None:
    assert not is_skip_line(line)


# --- join_paragraphs ---


def test_join_simple_two_lines() -> None:
    src = "línea uno\nlínea dos"
    out = join_paragraphs(src)
    assert "línea uno línea dos" in out


def test_join_paragraph_8_lines_roadmap() -> None:
    """Caso literal del roadmap: párrafo de 8 líneas → 1 línea."""
    src = (
        "Esta es la primera línea del párrafo,\n"
        "segunda línea continúa sin terminar\n"
        "y sigue hacia la tercera línea,\n"
        "cuarta línea sin punto final\n"
        "quinta línea también continúa\n"
        "sexta línea introductoria\n"
        "séptima línea con más texto,\n"
        "octava línea que cierra el párrafo\n"
    )
    out = join_paragraphs(src)
    non_blank = [line for line in out.splitlines() if line.strip()]
    assert len(non_blank) == 1
    assert "octava línea que cierra el párrafo" in out


def test_no_join_with_period() -> None:
    src = "Párrafo uno.\nPárrafo dos."
    out = join_paragraphs(src)
    non_blank = [line for line in out.splitlines() if line.strip()]
    assert len(non_blank) == 2


def test_no_join_with_blank_line() -> None:
    src = "línea uno\n\nlínea dos"
    out = join_paragraphs(src)
    non_blank = [line for line in out.splitlines() if line.strip()]
    assert len(non_blank) == 2


def test_no_join_atx_heading() -> None:
    src = "línea de texto\n# Heading\nmás texto"
    out = join_paragraphs(src)
    lines = [line for line in out.splitlines() if line.strip()]
    assert "# Heading" in lines
    assert len(lines) == 3


def test_no_join_list_item() -> None:
    src = "línea de texto\n- item\n- otro"
    out = join_paragraphs(src)
    lines = [line for line in out.splitlines() if line.strip()]
    assert "- item" in lines
    assert len(lines) >= 3


def test_no_join_blockquote() -> None:
    src = "línea de texto\n> quote"
    out = join_paragraphs(src)
    lines = [line for line in out.splitlines() if line.strip()]
    assert "> quote" in lines
    assert len(lines) == 2


def test_join_opening_quote_dialogue() -> None:
    src = 'She said, "Hello\nworld."'
    out = join_paragraphs(src)
    assert "Hello world" in out


def test_join_preserves_inside_fences() -> None:
    src = "before\n```\nlínea uno\nlínea dos\n```\nafter"
    out = join_paragraphs(src)
    fenced = out.split("```")[1]
    assert "línea uno\nlínea dos" in fenced


def test_join_multiple_paragraphs_in_text() -> None:
    src = (
        "primer párrafo línea uno\n"
        "primer párrafo línea dos\n"
        "\n"
        "segundo párrafo línea uno\n"
        "segundo párrafo línea dos."
    )
    out = join_paragraphs(src)
    paragraphs = [p for p in out.split("\n\n") if p.strip()]
    assert len(paragraphs) == 2


def test_join_normalizes_multiple_spaces() -> None:
    src = "línea uno\nlínea dos"
    out = join_paragraphs(src)
    assert "  " not in out


def test_join_empty_text() -> None:
    assert join_paragraphs("") == ""


def test_no_join_just_prose() -> None:
    src = "Párrafo uno.\nPárrafo dos.\nPárrafo tres."
    out = join_paragraphs(src)
    non_blank = [line for line in out.splitlines() if line.strip()]
    assert len(non_blank) == 3


def test_join_with_comma_continuation() -> None:
    src = "Empezó diciendo,\nseguido de más texto."
    out = join_paragraphs(src)
    assert "Empezó diciendo," in out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1


def test_join_with_question_continuation() -> None:
    """Línea con ? + siguiente lowercase se une (continuación)."""
    src = "¿Cómo estás?\nbien, gracias."
    out = join_paragraphs(src)
    assert "¿Cómo estás? bien, gracias." in out


def test_join_preserves_blank_lines_between_paragraphs() -> None:
    src = "párrafo uno\n\npárrafo dos"
    out = join_paragraphs(src)
    assert "\n\n" in out or out.count("\n") >= 1


def test_join_only_trailing_blank_lines() -> None:
    src = "línea uno\nlínea dos\n\n"
    out = join_paragraphs(src)
    assert "línea uno línea dos" in out


# --- ParagraphJoinsCleaner ---


def test_paragraph_joins_cleaner_default_name() -> None:
    assert ParagraphJoinsCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "paragraph_joins"


def test_paragraph_joins_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(ParagraphJoinsCleaner(), Cleaner)


def test_paragraph_joins_cleaner_pipeline_integration(tmp_path: Path) -> None:
    src = "línea uno\nlínea dos"
    pipeline = Pipeline(cleaners=(ParagraphJoinsCleaner(),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert "línea uno línea dos" in text
    assert stats[0].name == "paragraph_joins"


def test_paragraph_joins_cleaner_disabled(tmp_path: Path) -> None:
    src = "línea uno\nlínea dos"
    pipeline = Pipeline(cleaners=(ParagraphJoinsCleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_paragraph_joins_cleaner_empty_input(tmp_path: Path) -> None:
    result = ParagraphJoinsCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_paragraph_joins_cleaner_no_change_when_no_joins(tmp_path: Path) -> None:
    src = "Párrafo uno.\nPárrafo dos.\nPárrafo tres."
    result = ParagraphJoinsCleaner().run(src, _ctx(tmp_path))
    assert result.text == src
    assert result.changes == 0


def test_paragraph_joins_cleaner_reports_count(tmp_path: Path) -> None:
    src = "línea uno\nlínea dos\nlínea tres"
    result = ParagraphJoinsCleaner().run(src, _ctx(tmp_path))
    assert result.changes >= 1


# --- constants ---


def test_terminal_punctuation_chars() -> None:
    assert TERMINAL_PUNCTUATION == ".:;"


def test_opening_brackets_chars() -> None:
    assert OPENING_BRACKETS == '(["'
