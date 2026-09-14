"""Reparación de notas al pie (D13).

Convierte marcadores en cuerpo (superscripts ``¹²³…`` o ``[1]`` al final
de párrafo) y el bloque de definiciones numeradas al final del documento
al formato GFM ``[^N]`` / ``[^N]:``.

Decisiones de diseño (ver plan):
- Superscripts multi-digit (``¹²``) se splitean en ``[^1][^2]``.
- ``[N]`` solo es marker al final de línea.
- Orphans (markers sin def o defs sin marker) se preservan.
- Respeta fences ```` ``` ```` y ``~~~``.
- Idempotente: deduplica refs adyacentes (``[^1][^1]`` → ``[^1]``).
"""

from __future__ import annotations

import re

from capmd.clean._fences import split_outside_fences
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "BRACKET_MARKER_RE",
    "DEFAULT_NAME",
    "SUPERSCRIPT_DIGITS",
    "SUPERSCRIPT_RE",
    "FootnotesCleaner",
    "detect_footnote_block",
    "normalize_markers",
    "parse_footnote_definitions",
    "render_gfm_footnotes",
    "repair_footnotes",
]

DEFAULT_NAME = "footnotes"

SUPERSCRIPT_DIGITS: dict[str, str] = {
    "⁰": "0",  # U+2070
    "¹": "1",  # U+00B9
    "²": "2",  # U+00B2
    "³": "3",  # U+00B3
    "⁴": "4",  # U+2074
    "⁵": "5",  # U+2075
    "⁶": "6",  # U+2076
    "⁷": "7",  # U+2077
    "⁸": "8",  # U+2078
    "⁹": "9",  # U+2079
}

_SUPERSCRIPT_CHARS = "".join(SUPERSCRIPT_DIGITS.keys())
SUPERSCRIPT_RE = re.compile(f"[{_SUPERSCRIPT_CHARS}]+")
BRACKET_MARKER_RE = re.compile(r"\[(\d+)\](?=\s*$|\s*\n)")
_NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+[.)])\s+(.*)$")
_EXISTING_REF_RE = re.compile(r"\[\^\d+\]")


def _dedupe_adjacent_refs(text: str) -> str:
    """Colapsa ``[^N][^N]`` (con whitespace opcional) a una sola ``[^N]``.

    Solo deduplica refs con el MISMO número; refs distintas se preservan.
    """
    pattern = re.compile(r"(\[\^(\d+)\])(?:\s*\[\^\2\])+")
    while True:
        new = pattern.sub(r"\1", text)
        if new == text:
            return new
        text = new


def _is_numbered_item(line: str) -> bool:
    return _NUMBERED_ITEM_RE.match(line) is not None


def detect_footnote_block(text: str) -> tuple[int, int] | None:
    """Detecta el bloque numerado al final del documento.

    Devuelve ``(start, end_exclusive)`` o ``None`` si no hay.
    El bloque son las líneas numeradas consecutivas (con blanks opcionales
    entre ellas) al final del documento, terminando con la última línea
    numerada.
    """
    lines = text.splitlines(keepends=True)
    n = len(lines)
    if n == 0:
        return None
    i = n - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    if i < 0 or not _is_numbered_item(lines[i]):
        return None
    end_idx = i
    first_idx = end_idx
    while first_idx > 0 and (
        _is_numbered_item(lines[first_idx - 1]) or lines[first_idx - 1].strip() == ""
    ):
        first_idx -= 1
    j = first_idx
    while j <= end_idx and not _is_numbered_item(lines[j]):
        j += 1
    if j > end_idx:
        return None
    return j, end_idx + 1


def parse_footnote_definitions(text: str) -> dict[int, str]:
    """Extrae ``{n: text}`` del bloque numerado al final de ``text``."""
    block = detect_footnote_block(text)
    if block is None:
        return {}
    start, end = block
    lines = text.splitlines(keepends=True)
    notes: dict[int, str] = {}
    for line in lines[start:end]:
        if line.strip() == "":
            continue
        m = _NUMBERED_ITEM_RE.match(line)
        if not m:
            continue
        num_part = m.group(1)
        content = m.group(2).rstrip()
        try:
            n = int(num_part.rstrip(".").rstrip(")"))
        except ValueError:
            continue
        if n not in notes:
            notes[n] = content
    return notes


def _replace_superscripts(match: re.Match[str]) -> str:
    chunk = match.group(0)
    return "".join(f"[^{SUPERSCRIPT_DIGITS[c]}]" for c in chunk)


def _replace_brackets(match: re.Match[str]) -> str:
    return f"[^{match.group(1)}]"


def normalize_markers(text: str) -> tuple[str, int]:
    """Reemplaza supers y bracket-markers por ``[^N]``. Respeta fences.

    Devuelve ``(texto, n_replacements)`` donde ``n_replacements`` cuenta
    markers individuales (cada supers digit o cada bracket match).
    """
    if not text:
        return text, 0

    segments = split_outside_fences(text)
    out: list[str] = []
    n_replacements = 0
    for seg, in_fence in segments:
        if in_fence:
            out.append(seg)
            continue
        before = seg
        seg, n_super = SUPERSCRIPT_RE.subn(_replace_superscripts, seg)
        seg, n_bracket = BRACKET_MARKER_RE.subn(_replace_brackets, seg)
        seg = _dedupe_adjacent_refs(seg)
        if seg != before:
            n_replacements += n_super + n_bracket
        out.append(seg)
    return "".join(out), n_replacements


def render_gfm_footnotes(notes: dict[int, str]) -> str:
    """Renderiza ``[^N]: text\\n[^N]: text\\n...``."""
    if not notes:
        return ""
    lines = [f"[^{n}]: {text}" for n, text in sorted(notes.items())]
    return "\n".join(lines)


def repair_footnotes(text: str) -> tuple[str, int, int]:
    """Normaliza markers y consolida definiciones al final.

    Devuelve ``(texto, n_markers, n_definitions)``.
    """
    if not text:
        return text, 0, 0

    body, n_markers = normalize_markers(text)
    if n_markers == 0:
        return text, 0, 0

    notes = parse_footnote_definitions(body)
    block = detect_footnote_block(body)

    if block is None:
        return body, n_markers, 0

    start, end = block
    lines = body.splitlines(keepends=True)
    body_without_block = "".join(lines[:start] + lines[end:]).rstrip("\n")
    rendered = render_gfm_footnotes(notes)
    if not rendered:
        return body_without_block + "\n", n_markers, 0
    return body_without_block + "\n\n" + rendered + "\n", n_markers, len(notes)


class FootnotesCleaner(Cleaner):
    """Cleaner que normaliza notas al pie a formato GFM."""

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    def _apply(self, md: str, ctx: CleanContext) -> CleanResult:
        if not md:
            return CleanResult(text=md, changes=0)
        out, n_markers, n_defs = repair_footnotes(md)
        if out == md:
            return CleanResult(text=md, changes=0)
        return CleanResult(text=out, changes=n_markers + n_defs)
