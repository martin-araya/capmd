"""Code blocks: detección y wrapping en ```` ``` ```` (D9).

Dos estrategias combinadas:

1. **Font-name aware** (cuando ``page_font_names`` está disponible):
   líneas en las que la mayoría de chars vienen de una fuente
   monoespaciada (Courier, Consolas, Menlo, etc.).

2. **Indent-based** (siempre activo): líneas indentadas con 4+
   espacios o un tab.

Lenguaje inferido por keyword scoring sobre las primeras líneas del
bloque (Rust, Go, Python, JS, TS, C, C++, Java, Bash, SQL).
"""

from __future__ import annotations

import re

from capmd.clean._code_keywords import get_compiled_keywords
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext
from capmd.convert.page_markers import join_pages, split_by_page_markers

__all__ = [
    "DEFAULT_NAME",
    "MONOSPACE_FONT_HINTS",
    "MONOSPACE_THRESHOLD",
    "CodeBlockCleaner",
    "infer_language",
    "is_indented_code_line",
    "is_monospace_line",
    "wrap_code_blocks",
]

DEFAULT_NAME = "code_blocks"

MONOSPACE_FONT_HINTS: tuple[str, ...] = (
    "Courier",
    "Consolas",
    "Menlo",
    "Monaco",
    "RobotoMono",
    "Roboto Mono",
    "SourceCodePro",
    "Source Code Pro",
    "LiberationMono",
    "DejaVuSansMono",
    "Inconsolata",
    "Andale Mono",
    "PT Mono",
)

MONOSPACE_THRESHOLD = 0.8

_FENCE_RE = re.compile(r"^(?:`{3,}|~{3,})")
_INDENT_RE = re.compile(r"^(?:    |\t)")
_BLANK_LINE_RE = re.compile(r"^\s*$")
_HEADING_LINE_RE = re.compile(r"^\s*#{1,6}\s")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _is_monospace_font(name: str) -> bool:
    if not name:
        return False
    lower = name.lower()
    return any(hint.lower() in lower for hint in MONOSPACE_FONT_HINTS)


def is_indented_code_line(line: str) -> bool:
    """True si la línea está indentada con 4+ espacios o un tab."""
    if not line or not line.strip():
        return False
    if _HEADING_LINE_RE.match(line):
        return False
    if _LIST_ITEM_RE.match(line):
        return False
    return bool(_INDENT_RE.match(line))


def _find_line_char_index(line: str, page_text: str, search_from: int) -> int | None:
    stripped = line.strip()
    if not stripped:
        return None
    return page_text.find(stripped, search_from)


def is_monospace_line(
    line: str,
    page_font_names: tuple[str, ...] | None,
    search_from: int,
    page_text: str,
) -> bool:
    """True si ``line`` tiene >=80% chars de fuente monoespaciada."""
    if page_font_names is None or not page_font_names:
        return False
    if not line or not line.strip():
        return False
    char_idx = _find_line_char_index(line, page_text, search_from)
    if char_idx is None:
        return False
    stripped = line.strip()
    end = char_idx + len(stripped)
    if end > len(page_font_names):
        end = len(page_font_names)
    window = page_font_names[char_idx:end]
    if not window:
        return False
    mono = sum(1 for name in window if _is_monospace_font(name))
    return mono / len(window) >= MONOSPACE_THRESHOLD


def infer_language(code: str) -> str:
    """Devuelve el lenguaje inferido o '' si no se puede."""
    if not code or not code.strip():
        return ""
    head = "\n".join(code.splitlines()[:5])
    counts: dict[str, int] = {}
    for lang, patterns in get_compiled_keywords().items():
        counts[lang] = sum(1 for p in patterns if p.search(head))
    if not counts:
        return ""
    best_lang = max(counts, key=lambda k: counts[k])
    if counts[best_lang] == 0:
        return ""
    second = sorted(counts.values(), reverse=True)
    if len(second) > 1 and second[0] == second[1]:
        return ""
    return best_lang


def _wrap_block(lines: list[str]) -> list[str]:
    body = "\n".join(lines)
    lang = infer_language(body)
    fence = "```" + (lang if lang else "")
    return [fence, body, "```"]


def _process_page(
    page: str,
    page_font_names: tuple[str, ...] | None,
) -> tuple[list[str], int]:
    """Procesa una página y devuelve ``(output_lines, n_blocks_wrapped)``."""
    lines = page.splitlines()
    out: list[str] = []
    search_from = 0
    in_fence = False
    block: list[str] = []
    block_kind: str | None = None
    n_blocks = 0

    def flush() -> None:
        nonlocal block, block_kind
        if len(block) >= 2 and block_kind is not None:
            out.extend(_wrap_block(block))
            block = []
            block_kind = None
            return  # n_blocks incremented by caller via nonlocal pattern
        block = []
        block_kind = None

    for line in lines:
        if _FENCE_RE.match(line.lstrip()):
            if in_fence:
                out.append(line)
                in_fence = False
                continue
            if block:
                if len(block) >= 2 and block_kind is not None:
                    out.extend(_wrap_block(block))
                    n_blocks += 1
                else:
                    out.extend(block)
                block = []
                block_kind = None
            out.append(line)
            in_fence = True
            continue

        if in_fence:
            out.append(line)
            continue

        if _BLANK_LINE_RE.match(line):
            if block:
                if len(block) >= 2 and block_kind is not None:
                    out.extend(_wrap_block(block))
                    n_blocks += 1
                else:
                    out.extend(block)
                block = []
                block_kind = None
            out.append(line)
            continue

        is_mono = is_monospace_line(line, page_font_names, search_from, page)
        if is_mono:
            stripped = line.strip()
            if stripped:
                idx = _find_line_char_index(line, page, search_from)
                if idx is not None:
                    search_from = idx + len(stripped)
            kind = "mono"
        elif is_indented_code_line(line):
            kind = "indent"
        else:
            kind = None

        if kind is not None:
            if block_kind == kind:
                block.append(line)
            else:
                if block and block_kind is not None and len(block) >= 2:
                    out.extend(_wrap_block(block))
                    n_blocks += 1
                elif block:
                    out.extend(block)
                block = [line]
                block_kind = kind
        else:
            if block:
                if len(block) >= 2 and block_kind is not None:
                    out.extend(_wrap_block(block))
                    n_blocks += 1
                else:
                    out.extend(block)
                block = []
                block_kind = None
            out.append(line)

    if block:
        if len(block) >= 2 and block_kind is not None:
            out.extend(_wrap_block(block))
            n_blocks += 1
        else:
            out.extend(block)

    return out, n_blocks


def wrap_code_blocks(
    text: str,
    *,
    page_font_names: tuple[tuple[str, ...], ...] | None = None,
) -> str:
    """Envuelve bloques de código en ```` ``` ```` con lenguaje inferido."""
    if not text:
        return text

    if page_font_names is not None:
        pages = split_by_page_markers(text)
        out_pages: list[str] = []
        total = 0
        for idx, page in enumerate(pages):
            page_fonts = page_font_names[idx] if idx < len(page_font_names) else None
            out_lines, n = _process_page(page, page_fonts)
            out_pages.append("\n".join(out_lines))
            total += n
        return join_pages(out_pages)

    out_lines, _ = _process_page(text, None)
    return "\n".join(out_lines)


class CodeBlockCleaner(Cleaner):
    """Cleaner que detecta y envuelve bloques de código en fences."""

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    @staticmethod
    def _apply(md: str, ctx: CleanContext) -> CleanResult:
        if not md:
            return CleanResult(text=md, changes=0)
        before = md
        out = wrap_code_blocks(md, page_font_names=ctx.page_font_names)
        if out == before:
            return CleanResult(text=before, changes=0)
        before_blocks = before.count("\n```\n") + before.count("\n```")
        after_blocks = out.count("\n```\n") + out.count("\n```")
        n_added = max(0, after_blocks - before_blocks) // 2
        return CleanResult(text=out, changes=n_added)
