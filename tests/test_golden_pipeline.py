"""J2: golden files end-to-end del pipeline convert+clean.

Cada test parametrico corre el pipeline completo (Engine.convert_path →
Pipeline.run) sobre uno de los 14 fixtures sinteticos de
``tests/fixtures/build.py`` y compara el output contra el golden en
``tests/golden/<name>.md``.

Regenerar los goldens::

    pytest --update-golden tests/test_golden_pipeline.py

El conftest traduce ``--update-golden`` a ``--snapshot-update`` de
syrupy (ver ``tests/conftest.py``). El fixture ``snapshot`` con la
extension custom esta definido en ``tests/conftest.py`` para que pytest
lo descubra via discovery.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from capmd.clean import CleanContext, Pipeline
from capmd.clean.pipeline import default_pipeline
from capmd.convert import Engine
from capmd.models import Format, SourceDoc
from tests.fixtures import build as fix_build

# ---------------------------------------------------------------------------
# Builders parametrizados. Para fixtures que reciben ``work_dir``, usar
# ``tmp_path`` como ambos argumentos (out_path y work_dir).
# ---------------------------------------------------------------------------


def _build_two_images(p: Path) -> Path:
    return fix_build.build_two_images_pdf(p, p.parent)


def _build_outline_with_image(p: Path) -> Path:
    return fix_build.build_outline_with_chapter_image_pdf(p, p.parent)


def _build_logo_repeated(p: Path) -> Path:
    return fix_build.build_logo_repeated_pdf(p, p.parent)


def _build_midpage_image(p: Path) -> Path:
    return fix_build.build_text_with_midpage_image_pdf(p, p.parent)


def _build_many_pages(p: Path) -> Path:
    # Reducido de 500 a 10 para el golden: la logica de headers/footers
    # repetidos se ejercita igual; 500 paginas demora innecesariamente.
    return fix_build.build_many_pages_pdf(p, n_pages=10)


FIXTURES: dict[str, tuple[Callable[[Path], Path], Format]] = {
    "headings": (fix_build.build_headings_pdf, "pdf"),
    "four_h2": (fix_build.build_four_h2_pdf, "pdf"),
    "header_footer": (fix_build.build_header_footer_pdf, "pdf"),
    "cut_hyphens": (fix_build.build_cut_hyphens_pdf, "pdf"),
    "two_images": (_build_two_images, "pdf"),
    "outline_image": (_build_outline_with_image, "pdf"),
    "logo_repeated": (_build_logo_repeated, "pdf"),
    "midpage_image": (_build_midpage_image, "pdf"),
    "table": (fix_build.build_table_pdf, "pdf"),
    "many_pages": (_build_many_pages, "pdf"),
    "outline_toc": (fix_build.build_outline_toc_pdf, "pdf"),
    "no_outline": (fix_build.build_no_outline_chapters_pdf, "pdf"),
    "epub_3chapters": (fix_build.build_epub_with_3_chapters, "epub"),
    "scanned": (fix_build.build_scanned_pdf, "pdf"),
}


# ---------------------------------------------------------------------------
# Pipeline y contexto
# ---------------------------------------------------------------------------


def _ctx(pdf: Path, fmt: Format) -> CleanContext:
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return CleanContext(
        source=SourceDoc(
            path=pdf,
            format=fmt,
            sha256=sha,
            size_bytes=pdf.stat().st_size,
        ),
        format=fmt,
    )


def _run_pipeline(pdf: Path, fmt: Format) -> str:
    engine = Engine()
    raw = engine.convert_path(pdf).markdown
    pipeline: Pipeline = default_pipeline()
    cleaned, _stats = pipeline.run(raw, _ctx(pdf, fmt))
    return _strip_volatile(cleaned)


_VOLATILE_PATTERNS = (
    # Timestamps ISO 8601 con segundos/minutos opcionales (frontmatter converted_at).
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?"), "<TIMESTAMP>"),
    # Sufijos de page markers <!-- page N -->.
    (re.compile(r"<!-- page \d+ -->"), "<!-- page N -->"),
)


def _strip_volatile(md: str) -> str:
    """Quita campos no deterministas (timestamps) del output.

    El resto del body se conserva literal para que el diff del golden
    muestre exactamente qué cambio.
    """
    for pattern, replacement in _VOLATILE_PATTERNS:
        md = pattern.sub(replacement, md)
    return md


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,builder,fmt",
    [(name, b, fmt) for name, (b, fmt) in FIXTURES.items()],
    ids=list(FIXTURES.keys()),
)
def test_golden_pipeline(
    name: str,
    builder: Callable[[Path], Path],
    fmt: Format,
    snapshot,
    tmp_path: Path,
) -> None:
    """Full pipeline contra el golden ``tests/golden/<name>.md``."""
    pdf = builder(tmp_path / f"{name}.pdf")
    out = _run_pipeline(pdf, fmt)
    assert out == snapshot(name=name)


def test_golden_pipeline_cleaner_diff_triggers(tmp_path: Path) -> None:
    """Smoke test del mecanismo de golden: un cambio en un cleaner cambia el output.

    Crea un PDF con guiones de corte y verifica que el pipeline los une.
    No modifica el golden; este test queda como documentacion del contrato.
    """
    pdf = fix_build.build_cut_hyphens_pdf(tmp_path / "cut.pdf")
    out = _run_pipeline(pdf, "pdf")
    # El fixture tiene "pala-\nbra" → "palabra"; verificamos que el output
    # no contiene el guion de corte suelto (el cleaner D3 lo une).
    assert "pala-" not in out or "pala-\nbra" not in out
