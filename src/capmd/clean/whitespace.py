"""Cleaner de normalización de whitespace (D2).

Pipeline:
    strip_trailing_spaces
    → collapse_blank_lines (con pre-paso CRLF/CR → LF)
    → normalize_unicode_nfc
    → replace_ligatures
    → replace_rare_quotes

Las sub-funciones son puras y se exportan para que D10/D15 las
reutilicen desde code blocks o para tests focalizados.
"""

from __future__ import annotations

import re
import unicodedata

from capmd.clean._fences import apply_outside_fences
from capmd.clean._ligatures import LIGATURES_MAP
from capmd.clean._quotes import RARE_QUOTES_MAP
from capmd.clean.cleaner import Cleaner, CleanResult
from capmd.clean.context import CleanContext

__all__ = [
    "DEFAULT_NAME",
    "WhitespaceCleaner",
    "collapse_blank_lines",
    "normalize_line_endings",
    "normalize_unicode_nfc",
    "normalize_whitespace",
    "normalize_whitespace_preserve_fences",
    "replace_ligatures",
    "replace_rare_quotes",
    "strip_trailing_spaces",
]

DEFAULT_NAME = "whitespace"

_BLANK_RUN_RE = re.compile(r"\n{3,}")
_LF_NORMALIZE_RE = re.compile(r"\r\n?")
_TRAILING_RE = re.compile(r"[ \t]+(?=\n|$)")


def normalize_line_endings(text: str) -> str:
    """Normaliza CRLF y CR a LF."""
    if not text:
        return text
    return _LF_NORMALIZE_RE.sub("\n", text)


def strip_trailing_spaces(text: str) -> str:
    """Quita espacios y tabs al final de cada línea. Preserva el resto."""
    if not text:
        return text
    return _TRAILING_RE.sub("", text)


def collapse_blank_lines(text: str) -> str:
    """Normaliza CRLF/CR a LF y colapsa runs de 3+ ``\\n`` a exactamente 2."""
    if not text:
        return text
    text = _LF_NORMALIZE_RE.sub("\n", text)
    return _BLANK_RUN_RE.sub("\n\n", text)


def normalize_unicode_nfc(text: str) -> str:
    """Devuelve la forma canónica de composición del texto."""
    if not text:
        return text
    return unicodedata.normalize("NFC", text)


def replace_ligatures(text: str) -> str:
    """Reemplaza las ligaduras latin (U+FB01–U+FB06) por sus equivalentes ASCII."""
    if not text:
        return text
    for src, dst in LIGATURES_MAP.items():
        text = text.replace(src, dst)
    return text


def replace_rare_quotes(text: str) -> str:
    """Reemplaza comillas tipográficas exóticas. Conserva las curly estándar."""
    if not text:
        return text
    for src, dst in RARE_QUOTES_MAP.items():
        text = text.replace(src, dst)
    return text


def normalize_whitespace(md: str) -> str:
    """Aplica las 6 transformaciones en orden sobre ``md``."""
    text = normalize_line_endings(md)
    text = strip_trailing_spaces(text)
    text = collapse_blank_lines(text)
    text = normalize_unicode_nfc(text)
    text = replace_ligatures(text)
    text = replace_rare_quotes(text)
    return text


def normalize_whitespace_preserve_fences(md: str) -> str:
    """Como :func:`normalize_whitespace` pero respeta ```` ``` ```` y ``~~~``.

    Las transformaciones se aplican solo a segmentos fuera de fences;
    el contenido dentro de fences queda byte-a-byte intacto.
    """
    return apply_outside_fences(md, normalize_whitespace)


def _count_lines_with_trailing(text: str) -> int:
    return sum(1 for line in text.splitlines() if line != line.rstrip(" \t"))


def _count_collapsible_runs(text: str) -> int:
    return len(_BLANK_RUN_RE.findall(text))


def _count_changed_chars(before: str, after: str) -> int:
    if before == after:
        return 0
    n = min(len(before), len(after))
    diffs = sum(1 for a, b in zip(before[:n], after[:n], strict=False) if a != b)
    diffs += abs(len(before) - len(after))
    return diffs


def _count_occurrences(text: str, mapping: dict[str, str]) -> int:
    return sum(text.count(src) for src in mapping)


class WhitespaceCleaner(Cleaner):
    """Cleaner ``str -> str`` que normaliza whitespace.

    Reporta ``changes`` como suma de mutaciones por categoría:
    líneas con trailing whitespace + runs colapsados + chars cambiados
    por NFC + ligaduras + comillas raras.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__(
            name=DEFAULT_NAME,
            enabled=enabled,
            apply=self._apply,
        )

    @staticmethod
    def _apply(md: str, ctx: CleanContext) -> CleanResult:
        from capmd.clean._fences import split_outside_fences

        segments = split_outside_fences(md)
        out_parts: list[str] = []
        n_trail = 0
        n_blanks = 0
        n_unicode = 0
        n_ligatures = 0
        n_quotes = 0

        for seg, in_fence in segments:
            if in_fence:
                out_parts.append(seg)
                continue
            n_trail += _count_lines_with_trailing(seg)
            text = normalize_line_endings(seg)
            text = strip_trailing_spaces(text)
            n_blanks += _count_collapsible_runs(text)
            text = collapse_blank_lines(text)
            pre_nfc = text
            text = normalize_unicode_nfc(text)
            n_unicode += _count_changed_chars(pre_nfc, text)
            n_ligatures += _count_occurrences(text, LIGATURES_MAP)
            text = replace_ligatures(text)
            n_quotes += _count_occurrences(text, RARE_QUOTES_MAP)
            text = replace_rare_quotes(text)
            out_parts.append(text)

        changes = n_trail + n_blanks + n_unicode + n_ligatures + n_quotes
        return CleanResult(text="".join(out_parts), changes=changes)
