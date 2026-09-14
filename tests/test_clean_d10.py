"""Tests de D10: WhitespaceCleaner y DehyphenationCleaner preservan fences."""

from __future__ import annotations

from pathlib import Path

from capmd.clean import (
    CleanContext,
    CodeBlockCleaner,
    DehyphenationCleaner,
    Pipeline,
    WhitespaceCleaner,
    normalize_whitespace_preserve_fences,
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


# --- normalize_whitespace_preserve_fences (pure) ---


def test_normalize_preserve_fences_keeps_indented_code() -> None:
    src = 'prose\n\n```python\ndef foo():\n    if cond:\n        if cond2:\n            print("deep")\n```\n\nmore prose'
    out = normalize_whitespace_preserve_fences(src)
    assert "    if cond:" in out
    assert "        if cond2:" in out
    assert '            print("deep")' in out


def test_normalize_preserve_fences_does_not_strip_trailing_inside() -> None:
    """Líneas con trailing spaces dentro del fence se preservan intactas."""
    src = "```\nfoo   \nbar\t\n```"
    out = normalize_whitespace_preserve_fences(src)
    assert "foo   \n" in out
    assert "bar\t\n" in out


def test_normalize_preserve_fences_does_not_collapse_blanks_inside() -> None:
    src = "```\na\n\n\nb\n```"
    out = normalize_whitespace_preserve_fences(src)
    assert "a\n\n\nb\n" in out


def test_normalize_preserve_fences_preserves_nfc_outside() -> None:
    """NFC sí aplica fuera de fences."""
    decomposed = "cafe\u0301"
    src = f"{decomposed}\n```\nfoo\n```\n"
    out = normalize_whitespace_preserve_fences(src)
    assert out.startswith("café\n")


def test_normalize_preserve_fences_no_fence_works_like_normalize() -> None:
    from capmd.clean.whitespace import normalize_whitespace

    src = "trail   \nnormal"
    a = normalize_whitespace(src)
    b = normalize_whitespace_preserve_fences(src)
    assert a == b


def test_normalize_preserve_fences_tilde_fence() -> None:
    src = "~~~python\n    code\n~~~"
    out = normalize_whitespace_preserve_fences(src)
    assert "    code\n" in out


def test_normalize_preserve_fences_with_language_hint() -> None:
    src = "```python\n    indented\n```"
    out = normalize_whitespace_preserve_fences(src)
    assert out.startswith("```python")
    assert "    indented" in out


def test_normalize_preserve_fences_empty_body() -> None:
    src = "before\n```\n```\nafter"
    out = normalize_whitespace_preserve_fences(src)
    assert out == src


def test_normalize_preserve_fences_unclosed_eats_rest() -> None:
    """Fence sin cierre: todo lo siguiente queda dentro."""
    src = "before\n```\ninside\nforever"
    out = normalize_whitespace_preserve_fences(src)
    assert "inside\nforever" in out


# --- WhitespaceCleaner integration ---


def test_whitespace_cleaner_preserves_4_levels_of_indent(tmp_path: Path) -> None:
    """Caso literal del roadmap."""
    src = (
        "Intro prose here.\n\n"
        "```python\n"
        "def foo():\n"
        "    if cond:\n"
        "        if cond2:\n"
        '            print("deep")\n'
        "```\n\n"
        "More prose."
    )
    result = WhitespaceCleaner().run(src, _ctx(tmp_path))

    assert "    if cond:" in result.text
    assert "        if cond2:" in result.text
    assert '            print("deep")' in result.text
    assert "Intro prose here." in result.text
    assert "More prose." in result.text


def test_whitespace_cleaner_does_not_strip_trailing_inside_fence(tmp_path: Path) -> None:
    src = "```\nfoo   \nbar\t\n```"
    result = WhitespaceCleaner().run(src, _ctx(tmp_path))
    assert "foo   \n" in result.text
    assert "bar\t\n" in result.text


def test_whitespace_cleaner_does_not_collapse_blanks_inside_fence(tmp_path: Path) -> None:
    src = "```\na\n\n\nb\n```"
    result = WhitespaceCleaner().run(src, _ctx(tmp_path))
    assert "a\n\n\nb\n" in result.text


def test_whitespace_cleaner_still_processes_outside(tmp_path: Path) -> None:
    """Prose afuera sí se normaliza; el fence interior no."""
    src = "trail   \n\n```\nkeep   \n```\n\nmore trail\t"
    result = WhitespaceCleaner().run(src, _ctx(tmp_path))
    assert "keep   \n" in result.text
    assert result.text.rstrip().endswith("more trail")
    assert "\n\n\n" not in result.text


def test_whitespace_cleaner_count_excludes_fence_internal(tmp_path: Path) -> None:
    """Si todo el cambio está dentro del fence, changes == 0."""
    src = "```\n   only inside\n```"
    result = WhitespaceCleaner().run(src, _ctx(tmp_path))
    assert result.changes == 0


def test_whitespace_cleaner_with_tilde_fence(tmp_path: Path) -> None:
    src = "~~~python\n    code\n~~~"
    result = WhitespaceCleaner().run(src, _ctx(tmp_path))
    assert "    code" in result.text


def test_whitespace_cleaner_no_fence_behavior_unchanged(tmp_path: Path) -> None:
    src = "trail   \nnormal"
    result = WhitespaceCleaner().run(src, _ctx(tmp_path))
    assert "trail\n" in result.text
    assert result.changes >= 1


# --- DehyphenationCleaner integration ---


def test_dehyphenation_cleaner_skips_inside_fence(tmp_path: Path) -> None:
    """Un patrón ``pala-\\nbra`` dentro de fence NO se une."""
    src = "before\n```\npala-\nbra\n```\nafter"
    result = DehyphenationCleaner().run(src, _ctx(tmp_path))
    assert "pala-\nbra" in result.text or "pala-bra" in result.text


def test_dehyphenation_cleaner_still_works_outside_fence(tmp_path: Path) -> None:
    """El mismo patrón fuera de fence sí se une."""
    src = "pala-\nbra is a word"
    result = DehyphenationCleaner().run(src, _ctx(tmp_path))
    assert result.text == "palabra is a word"


def test_dehyphenation_cleaner_mixed_fence_and_prose(tmp_path: Path) -> None:
    src = "pala-\nbra outside\n```\nkeep-\ning\n```\nmore outside\n"
    result = DehyphenationCleaner().run(src, _ctx(tmp_path))
    assert "palabra outside" in result.text
    assert "keep-\ning" in result.text
    assert "more outside" in result.text


# --- Pipeline integration ---


def test_full_pipeline_preserves_4_levels_indent(tmp_path: Path) -> None:
    """Pipeline completo WhitespaceCleaner → CodeBlockCleaner preserva indentación."""
    src = (
        "Intro.\n\n"
        "```python\n"
        "def foo():\n"
        "    if cond:\n"
        "        if cond2:\n"
        '            print("deep")\n'
        "```\n\n"
        "Outro."
    )
    pipeline = Pipeline(cleaners=(WhitespaceCleaner(), CodeBlockCleaner()))
    text, stats = pipeline.run(src, _ctx(tmp_path))

    assert "    if cond:" in text
    assert "        if cond2:" in text
    assert '            print("deep")' in text
    assert "Intro." in text
    assert "Outro." in text
    assert stats[0].name == "whitespace"
    assert stats[1].name == "code_blocks"


def test_pipeline_idempotent_on_fenced_code(tmp_path: Path) -> None:
    src = "before\n```python\n    if a:\n        if b:\n            print(c)\n```\nafter"
    pipeline = Pipeline(cleaners=(WhitespaceCleaner(), DehyphenationCleaner()))
    once, _ = pipeline.run(src, _ctx(tmp_path))
    twice, _ = pipeline.run(once, _ctx(tmp_path))
    assert once == twice


def test_pipeline_no_fence_works_as_before(tmp_path: Path) -> None:
    """Sin fences, comportamiento idéntico al pre-D10."""
    src = "trail   \nnormal\n"
    pipeline = Pipeline(cleaners=(WhitespaceCleaner(),))
    text, _ = pipeline.run(src, _ctx(tmp_path))
    assert "trail\n" in text


# --- Edge cases ---


def test_pipeline_handles_unclosed_fence(tmp_path: Path) -> None:
    src = "before\n```\n   inside forever"
    text, _ = Pipeline(cleaners=(WhitespaceCleaner(),)).run(src, _ctx(tmp_path))
    assert "inside forever" in text
