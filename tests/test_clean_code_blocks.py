"""Tests del cleaner de code blocks (D9)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from capmd.clean import (
    CleanContext,
    CodeBlockCleaner,
    Pipeline,
    infer_language,
    is_indented_code_line,
    is_monospace_line,
    wrap_code_blocks,
)
from capmd.clean.code_blocks import (
    DEFAULT_NAME,
    MONOSPACE_FONT_HINTS,
    MONOSPACE_THRESHOLD,
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


def _ctx(tmp_path: Path, **kwargs: object) -> CleanContext:
    return CleanContext(source=_make_source(tmp_path), format="pdf", **kwargs)


# --- is_indented_code_line ---


@pytest.mark.parametrize(
    "line",
    [
        "    def foo(): pass",
        "\tdef foo(): pass",
        "        indented body",
    ],
)
def test_indented_code_line_true(line: str) -> None:
    assert is_indented_code_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "def foo(): pass",  # not indented
        "  two spaces",  # less than 4
        "",
        "   ",  # whitespace only
        "# heading",  # heading
        "   # indented heading",  # indented heading
        "- list item",
        "  - list item",
        "1. list item",
    ],
)
def test_indented_code_line_false(line: str) -> None:
    assert not is_indented_code_line(line)


# --- is_monospace_line ---


def test_monospace_line_all_courier() -> None:
    line = "let x = 1;"
    page_text = "abc\n" + line
    char_idx = page_text.find("let")
    end = char_idx + len(line)
    page_font_names = ("Helvetica",) * char_idx + ("Courier New",) * len(line)
    page_font_names += ("Helvetica",) * max(0, len(page_text) - end)
    assert is_monospace_line(line, page_font_names, 0, page_text)


def test_monospace_line_all_proportional() -> None:
    line = "Hello world"
    page_text = line
    page_font_names = ("Helvetica",) * len(line)
    assert not is_monospace_line(line, page_font_names, 0, page_text)


def test_monospace_line_below_threshold() -> None:
    line = "abcde"
    page_text = line
    page_font_names = ("Courier",) + ("Helvetica",) * 4
    assert not is_monospace_line(page_text, page_font_names, 0, page_text)


def test_monospace_line_above_threshold() -> None:
    line = "abcde"
    page_text = line
    page_font_names = ("Courier",) * 4 + ("Helvetica",)
    assert is_monospace_line(page_text, page_font_names, 0, page_text)


def test_monospace_line_no_page_fonts() -> None:
    assert not is_monospace_line("anything", None, 0, "anything")


def test_monospace_font_hints_nonempty() -> None:
    assert len(MONOSPACE_FONT_HINTS) >= 5
    assert MONOSPACE_THRESHOLD == 0.8


# --- infer_language ---


def test_infer_rust() -> None:
    code = "fn main() { let mut x = 1; impl Foo for Bar { } ::path }"
    assert infer_language(code) == "rust"


def test_infer_go() -> None:
    code = "package main\nfunc foo() { defer cleanup() }"
    assert infer_language(code) == "go"


def test_infer_python() -> None:
    code = "def foo():\n    import os\nclass Bar:\n    pass"
    assert infer_language(code) == "python"


def test_infer_javascript() -> None:
    code = "const x = () => {\n  console.log('hi');\n}"
    assert infer_language(code) == "javascript"


def test_infer_typescript() -> None:
    code = "interface Foo { x: string; }\ntype Bar = number;"
    assert infer_language(code) == "typescript"


def test_infer_c() -> None:
    code = '#include <stdio.h>\nint main() { printf("hi"); }'
    assert infer_language(code) == "c"


def test_infer_cpp() -> None:
    code = '#include <iostream>\nstd::cout << "hi";\ntemplate <typename T>'
    assert infer_language(code) == "cpp"


def test_infer_java() -> None:
    code = (
        "public class Foo {\n  public static void main(String[] args) { System.out.println(); }\n}"
    )
    assert infer_language(code) == "java"


def test_infer_bash() -> None:
    code = "#!/bin/bash\necho hi\nif [ -f foo ]; then\n  echo y\nesac\nfi\ndone"
    assert infer_language(code) == "bash"


def test_infer_sql() -> None:
    code = "SELECT * FROM users WHERE active = true;\nINSERT INTO logs VALUES (1);"
    assert infer_language(code) == "sql"


def test_infer_empty_for_prose() -> None:
    assert infer_language("Just some regular prose text without any keywords.") == ""


def test_infer_empty_for_empty_string() -> None:
    assert infer_language("") == ""


# --- wrap_code_blocks: indent ---


def test_wrap_indented_python_block() -> None:
    src = "intro\n    def foo():\n        pass\n    def bar():\n        pass\noutro"
    out = wrap_code_blocks(src)
    assert "```python" in out
    assert "def foo():" in out
    assert "def bar():" in out
    assert "```" in out


def test_wrap_indented_block_short_two_lines() -> None:
    src = "intro\n    a = 1\n    b = 2\noutro"
    out = wrap_code_blocks(src)
    assert "```" in out


def test_indented_block_not_treated_when_one_line() -> None:
    src = "intro\n    def foo():\noutro"
    out = wrap_code_blocks(src)
    assert "```" not in out


def test_no_indent_no_wrap() -> None:
    src = "Just regular paragraph text.\nNo indentation anywhere."
    assert wrap_code_blocks(src) == src


def test_multiline_indented_block_with_blank_terminates() -> None:
    src = "intro\n    a = 1\n    b = 2\n\nAfter block."
    out = wrap_code_blocks(src)
    assert "```" in out
    assert "After block." in out


def test_merge_consecutive_indented_lines() -> None:
    src = "    a\n    b\n    c\n    d"
    out = wrap_code_blocks(src)
    assert out.count("```") == 2


def test_no_double_wrap_existing_fence() -> None:
    src = "intro\n```rust\nfn main() {}\n```\noutro"
    assert wrap_code_blocks(src) == src


def test_no_double_wrap_existing_tilde_fence() -> None:
    src = "intro\n~~~python\ndef foo(): pass\n~~~\noutro"
    assert wrap_code_blocks(src) == src


def test_wrap_block_unknown_lang_no_fence_lang() -> None:
    src = "    foo bar baz\n    qux quux corge"
    out = wrap_code_blocks(src)
    assert "```\n" in out
    assert "```python" not in out
    assert "```rust" not in out


# --- wrap_code_blocks: monospace ---


def test_wrap_monospace_block_via_font_names() -> None:
    src = "intro\nlet x = 1\nfn foo()\noutro"
    src_page = src
    intro_end = src_page.find("let")
    outro_start = src_page.find("outro")
    mono_section = src_page[intro_end:outro_start]
    page_font_names: list[str] = []
    page_font_names += ["Helvetica"] * intro_end
    page_font_names += ["Courier New"] * len(mono_section)
    page_font_names += ["Helvetica"] * (len(src_page) - outro_start)
    out = wrap_code_blocks(src_page, page_font_names=(tuple(page_font_names),))
    assert "```rust" in out
    assert "fn foo()" in out


def test_no_wrap_when_font_not_monospace() -> None:
    src = "Hello world\nAnother line\nThird line"
    page_font_names = ("Helvetica",) * len(src)
    out = wrap_code_blocks(src, page_font_names=(page_font_names,))
    assert "```" not in out


# --- wrap_code_blocks: edge cases ---


def test_wrap_empty_text() -> None:
    assert wrap_code_blocks("") == ""


def test_wrap_with_no_font_names_falls_back_to_indent() -> None:
    src = "    def foo(): pass\n    x = 1"
    out = wrap_code_blocks(src)
    assert "```python" in out


def test_wrap_block_spanning_two_pages() -> None:
    pages = ["    def foo():\n        pass\n<!-- page 2 -->\n        continue"]
    md = "intro\n" + pages[0]
    out = wrap_code_blocks(md)
    assert "```python" in out


# --- CodeBlockCleaner ---


def test_code_block_cleaner_default_name() -> None:
    assert CodeBlockCleaner().name == DEFAULT_NAME
    assert DEFAULT_NAME == "code_blocks"


def test_code_block_cleaner_is_a_cleaner() -> None:
    from capmd.clean import Cleaner

    assert isinstance(CodeBlockCleaner(), Cleaner)


def test_code_block_cleaner_pipeline_integration(tmp_path: Path) -> None:
    pipeline = Pipeline(cleaners=(CodeBlockCleaner(),))
    md = "intro\n    def foo():\n        pass\n    def bar():\n        pass\noutro"
    text, stats = pipeline.run(md, _ctx(tmp_path))
    assert "```python" in text
    assert len(stats) == 1
    assert stats[0].name == "code_blocks"
    assert stats[0].changes >= 1


def test_code_block_cleaner_disabled(tmp_path: Path) -> None:
    src = "intro\n    def foo():\n        pass\noutro"
    pipeline = Pipeline(cleaners=(CodeBlockCleaner(enabled=False),))
    text, stats = pipeline.run(src, _ctx(tmp_path))
    assert text == src
    assert stats[0].enabled is False
    assert stats[0].changes == 0


def test_code_block_cleaner_empty_input(tmp_path: Path) -> None:
    result = CodeBlockCleaner().run("", _ctx(tmp_path))
    assert result.text == ""
    assert result.changes == 0


def test_code_block_cleaner_no_code_no_change(tmp_path: Path) -> None:
    src = "Just regular text without code blocks."
    result = CodeBlockCleaner().run(src, _ctx(tmp_path))
    assert result.text == src
    assert result.changes == 0


def test_code_block_cleaner_uses_page_font_names_from_context(tmp_path: Path) -> None:
    src = "intro\nlet x = 1\nfn foo()\noutro"
    page_text = src
    page_font_names = (
        "Helvetica",
        "Helvetica",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Courier New",
        "Helvetica",
        "Helvetica",
    )
    strict_match = len(page_text) == len(page_font_names)
    ctx = CleanContext(
        source=_make_source(tmp_path),
        format="pdf",
        page_font_names=(page_font_names,),
    )
    result = CodeBlockCleaner().run(src, ctx)
    if strict_match:
        assert "```rust" in result.text


# --- CleanContext ---


def test_clean_context_page_font_names_default_none(tmp_path: Path) -> None:
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf")
    assert ctx.page_font_names is None


def test_clean_context_page_font_names_accepts_tuple(tmp_path: Path) -> None:
    names = (("Courier", "Courier"), ("Helvetica",))
    ctx = CleanContext(source=_make_source(tmp_path), format="pdf", page_font_names=names)
    assert ctx.page_font_names == names


def test_clean_context_is_frozen_with_page_font_names(tmp_path: Path) -> None:
    ctx = CleanContext(
        source=_make_source(tmp_path),
        format="pdf",
        page_font_names=(("Courier",),),
    )
    with pytest.raises(FrozenInstanceError):
        ctx.page_font_names = None
