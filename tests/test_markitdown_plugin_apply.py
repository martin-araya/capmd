"""Verifica que el plugin de markitdown aplica la limpieza de capmd."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from markitdown import StreamInfo

from capmd.clean.context import CleanContext
from capmd.clean.pipeline import default_pipeline
from capmd.markitdown_plugin import MarkdownCleanerConverter
from capmd.models import SourceDoc

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "dirty_chapter.md"
SYNTHETIC_SHA = "0" * 64


def _build_context() -> CleanContext:
    """Mismo context que usa el plugin internamente para comparar output."""
    source = SourceDoc(
        path=FIXTURE_PATH,
        format="other",
        sha256=SYNTHETIC_SHA,
        size_bytes=0,
    )
    return CleanContext(source=source, format=source.format)


def _read_fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def _expected_cleaned() -> str:
    """Output esperado: lo que ``markitdown`` escribiría al disco.

    markitdown post-procesa cada resultado de converter con dos
    normalizaciones (``MarkItDown._convert``, líneas ~641-644):

    1. ``line.rstrip()`` en cada línea
    2. colapsa 3+ newlines a exactamente 2

    El plugin corre el mismo pipeline de capmd, pero el resultado pasa por
    esa normalización final. Comparamos contra ese output "como-escrito"
    para que el test refleje el comportamiento end-to-end real.
    """
    import re

    dirty = _read_fixture()
    pipeline = default_pipeline()
    cleaned, _stats = pipeline.run(dirty, _build_context())
    normalized = "\n".join(line.rstrip() for line in re.split(r"\r?\n", cleaned))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def _find_markitdown_cli():
    found = shutil.which("markitdown")
    if found:
        return found
    repo_venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "markitdown"
    if repo_venv.is_file():
        return str(repo_venv)
    return None


# ---------------------------------------------------------------------------
# Unit tests del converter
# ---------------------------------------------------------------------------


def test_accepts_markdown_extensions() -> None:
    """``accepts`` devuelve True para extensiones de markdown."""
    converter = MarkdownCleanerConverter()
    for ext in (".md", ".markdown", ".mkd", ".mkdn"):
        info = StreamInfo(extension=ext)
        assert converter.accepts(io.BytesIO(b""), info), f"debio aceptar {ext!r}"


def test_accepts_markdown_mimetypes() -> None:
    """``accepts`` devuelve True para mimetypes de markdown."""
    converter = MarkdownCleanerConverter()
    for mime in ("text/markdown", "text/x-markdown", "TEXT/MARKDOWN"):
        info = StreamInfo(mimetype=mime)
        assert converter.accepts(io.BytesIO(b""), info), f"debio aceptar {mime!r}"


def test_rejects_non_markdown_inputs() -> None:
    """``accepts`` devuelve False para PDF y otros formatos built-in."""
    converter = MarkdownCleanerConverter()
    for info in (
        StreamInfo(extension=".pdf"),
        StreamInfo(extension=".docx"),
        StreamInfo(extension=".html"),
        StreamInfo(mimetype="application/pdf"),
        StreamInfo(),  # sin ext ni mimetype
    ):
        assert not converter.accepts(io.BytesIO(b""), info), (
            f"no debio aceptar {info}"
        )


def test_convert_stream_runs_cleaners() -> None:
    """El converter produce el mismo output que el pipeline directo."""
    converter = MarkdownCleanerConverter()
    dirty = _read_fixture()
    stream = io.BytesIO(dirty.encode("utf-8"))
    info = StreamInfo(extension=".md", local_path=str(FIXTURE_PATH))

    result = converter.convert(stream, info)
    # El converter directo no aplica la normalización post-process de
    # markitdown (eso vive en MarkItDown._convert), así que comparamos
    # contra el output crudo del pipeline.

    pipeline = default_pipeline()
    raw_expected, _ = pipeline.run(dirty, _build_context())
    assert result.markdown == raw_expected


def test_convert_handles_empty_input() -> None:
    """Input vacío -> output vacío sin excepciones."""
    converter = MarkdownCleanerConverter()
    stream = io.BytesIO(b"")
    info = StreamInfo(extension=".md")
    result = converter.convert(stream, info)
    assert result.markdown == ""


def test_convert_handles_text_input() -> None:
    """Acepta streams ``str`` (no solo bytes)."""
    converter = MarkdownCleanerConverter()
    dirty = _read_fixture()

    class StrStream:
        def __init__(self, text: str) -> None:
            self._text = text

        def read(self) -> str:
            return self._text

    info = StreamInfo(extension=".md")
    result = converter.convert(StrStream(dirty), info)  # type: ignore[arg-type]


    pipeline = default_pipeline()
    raw_expected, _ = pipeline.run(dirty, _build_context())
    assert result.markdown == raw_expected


def test_plugin_does_not_fail_on_clean_input() -> None:
    """Si el input ya está limpio, el converter no rompe y devuelve markdown válido."""
    converter = MarkdownCleanerConverter()
    expected = _expected_cleaned()

    stream = io.BytesIO(expected.encode("utf-8"))
    info = StreamInfo(extension=".md")
    result = converter.convert(stream, info)
    # El output sigue siendo markdown no vacío.
    assert result.markdown
    assert "# Capítulo 3" in result.markdown
    assert "ownership" in result.markdown.lower()


# ---------------------------------------------------------------------------
# End-to-end via markitdown CLI
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def markitdown_cli() -> str:
    cli = _find_markitdown_cli()
    if cli is None:
        pytest.skip("markitdown CLI no disponible en el venv")
    return cli


def _run_markitdown(
    cli: str, args: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    return subprocess.run(
        [cli, *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


def test_markitdown_use_plugins_applies_cleanup(markitdown_cli: str, tmp_path: Path) -> None:
    """``markitdown archivo.md --use-plugins -o out.md`` aplica la limpieza."""
    out = tmp_path / "out.md"
    result = _run_markitdown(
        markitdown_cli,
        [str(FIXTURE_PATH), "--use-plugins", "-o", str(out)],
        cwd=tmp_path,
    )
    assert result.returncode == 0, (
        f"markitdown fallo:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert out.is_file(), f"no se creo {out}"
    produced = out.read_text(encoding="utf-8")
    assert produced == _expected_cleaned(), (
        f"el output del plugin no coincide con default_pipeline().run().\n"
        f"--- expected ---\n{_expected_cleaned()[:300]}\n"
        f"--- produced ---\n{produced[:300]}\n"
    )


def test_markitdown_use_plugins_two_pass_pdf_to_md(
    markitdown_cli: str, tmp_path: Path
) -> None:
    """Flujo en dos pasadas: ``markitdown .pdf`` -> ``markitdown .md --use-plugins``.

    Solo verifica el segundo paso (limpieza del .md) porque el primero depende
    del converter PDF. Usamos el .md fixture como input del primer paso para
    mantener el test determinista y no depender de PDF fixtures.
    """
    intermediate = tmp_path / "intermediate.md"
    final = tmp_path / "final.md"

    # Paso 1: .md -> .md sin plugins (identity).
    r1 = _run_markitdown(
        markitdown_cli,
        [str(FIXTURE_PATH), "-o", str(intermediate)],
        cwd=tmp_path,
    )
    assert r1.returncode == 0, r1.stderr
    assert intermediate.is_file()

    # Paso 2: el intermedio, esta vez con plugins.
    r2 = _run_markitdown(
        markitdown_cli,
        [str(intermediate), "--use-plugins", "-o", str(final)],
        cwd=tmp_path,
    )
    assert r2.returncode == 0, r2.stderr
    assert final.read_text(encoding="utf-8") == _expected_cleaned()


def test_markitdown_use_plugins_already_clean_keeps_structure(
    markitdown_cli: str, tmp_path: Path
) -> None:
    """Markdown ya limpio sigue produciendo markdown válido con sus headings."""
    expected = _expected_cleaned()
    already_clean = tmp_path / "already_clean.md"
    already_clean.write_text(expected, encoding="utf-8")

    out = tmp_path / "out.md"
    result = _run_markitdown(
        markitdown_cli,
        [str(already_clean), "--use-plugins", "-o", str(out)],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    produced = out.read_text(encoding="utf-8")
    # Headings clave siguen presentes.
    assert "# Capítulo 3: Ownership" in produced
    # Resumen sigue presente en el texto (puede estar como heading o como párrafo).
    assert "Resumen" in produced
    # Texto clave del capítulo sigue presente.
    assert "ownership" in produced.lower()
    assert "polimorfismo" in produced
