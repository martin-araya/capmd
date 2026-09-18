"""Comparador de motores para extracción de Markdown (K5).

API pública re-exportada desde :mod:`capmd.compare.motors` y
:mod:`capmd.compare.output`.
"""

from capmd.compare.motors import (
    CompareReport,
    MotorResult,
    MotorStatus,
    count_headings,
    count_words,
    detect_ocr_engines,
    parse_pages_string,
    run_compare,
    slice_pdf_to_tmpfile,
)
from capmd.compare.output import (
    RenderFormat,
    render_json,
    render_report,
    render_table,
)

__all__ = [
    "CompareReport",
    "MotorResult",
    "MotorStatus",
    "RenderFormat",
    "count_headings",
    "count_words",
    "detect_ocr_engines",
    "parse_pages_string",
    "render_json",
    "render_report",
    "render_table",
    "run_compare",
    "slice_pdf_to_tmpfile",
]
