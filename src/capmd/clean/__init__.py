"""Pipeline de limpieza de markdown.

Bloque D del roadmap. ``Pipeline`` ejecuta una secuencia ordenada de
``Cleaner`` sobre un string de markdown, devolviendo el texto final y la
lista de estadísticas por cleaner.
"""

from __future__ import annotations

from capmd.clean.cleaner import (
    Cleaner,
    CleanerStat,
    CleanResult,
    make_cleaner,
)
from capmd.clean.code_blocks import (
    CodeBlockCleaner,
    infer_language,
    is_indented_code_line,
    is_monospace_line,
    wrap_code_blocks,
)
from capmd.clean.context import CleanContext
from capmd.clean.footnotes import (
    FootnotesCleaner,
    detect_footnote_block,
    normalize_markers,
    parse_footnote_definitions,
    render_gfm_footnotes,
    repair_footnotes,
)
from capmd.clean.headers import (
    HeaderFooterCleaner,
    HeaderFooterOptions,
    detect_headers_footers,
    normalize_line,
    remove_headers_footers,
)
from capmd.clean.headings import (
    HeadingOptions,
    HeadingReconstructor,
    detect_heading_level,
    reconstruct_headings,
)
from capmd.clean.hyphens import DehyphenationCleaner, dehyphenate
from capmd.clean.lists import (
    ListsCleaner,
    repair_bullets,
    repair_lists,
    repair_numbered_lists,
)
from capmd.clean.page_numbers import (
    PageNumberCleaner,
    is_page_number_line,
    strip_page_number_lines,
)
from capmd.clean.paragraph_joins import (
    ParagraphJoinsCleaner,
    is_skip_line,
    join_paragraphs,
    should_join,
)
from capmd.clean.pipeline import Pipeline
from capmd.clean.single_h1 import (
    SingleH1Cleaner,
    count_atx_level,
    enforce_single_h1,
)
from capmd.clean.tables import (
    TableOptions,
    TablesCleaner,
    detect_table_blocks,
    render_gfm_table,
    repair_tables,
    score_block,
    split_row,
    wrap_unstructured_table,
)
from capmd.clean.whitespace import (
    WhitespaceCleaner,
    collapse_blank_lines,
    normalize_unicode_nfc,
    normalize_whitespace,
    normalize_whitespace_preserve_fences,
    replace_ligatures,
    replace_rare_quotes,
    strip_trailing_spaces,
)

__all__ = [
    "CleanContext",
    "CleanResult",
    "Cleaner",
    "CleanerStat",
    "CodeBlockCleaner",
    "DehyphenationCleaner",
    "FootnotesCleaner",
    "HeaderFooterCleaner",
    "HeaderFooterOptions",
    "HeadingOptions",
    "HeadingReconstructor",
    "ListsCleaner",
    "PageNumberCleaner",
    "ParagraphJoinsCleaner",
    "Pipeline",
    "SingleH1Cleaner",
    "TableOptions",
    "TablesCleaner",
    "WhitespaceCleaner",
    "collapse_blank_lines",
    "count_atx_level",
    "dehyphenate",
    "detect_footnote_block",
    "detect_headers_footers",
    "detect_heading_level",
    "detect_table_blocks",
    "enforce_single_h1",
    "infer_language",
    "is_indented_code_line",
    "is_monospace_line",
    "is_page_number_line",
    "is_skip_line",
    "join_paragraphs",
    "make_cleaner",
    "normalize_line",
    "normalize_markers",
    "normalize_unicode_nfc",
    "normalize_whitespace",
    "normalize_whitespace_preserve_fences",
    "parse_footnote_definitions",
    "reconstruct_headings",
    "remove_headers_footers",
    "render_gfm_footnotes",
    "render_gfm_table",
    "repair_bullets",
    "repair_footnotes",
    "repair_lists",
    "repair_numbered_lists",
    "repair_tables",
    "replace_ligatures",
    "replace_rare_quotes",
    "score_block",
    "should_join",
    "split_row",
    "strip_page_number_lines",
    "strip_trailing_spaces",
    "wrap_code_blocks",
    "wrap_unstructured_table",
]
