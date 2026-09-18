"""Motor runner para el comparador de motores (K5).

Cada motor (built-in, DocIntel, Content Understanding, OCR vía
tesseract/ocrmypdf) corre independiente y devuelve un
:class:`MotorResult` con su markdown crudo + métricas (palabras,
headings, tiempo). Ningún motor propaga excepciones: si falla, se
reporta como ``status="error"`` en el resultado.

El comparador :func:`run_compare` orquesta los motores disponibles
(siempre built-in; CU/DocIntel si sus env vars están seteadas; OCR si
tesseract/ocrmypdf están en PATH) y devuelve un :class:`CompareReport`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pypdfium2 as pdfium

from capmd.logging import get_logger

__all__ = [
    "CompareReport",
    "MotorResult",
    "MotorStatus",
    "count_headings",
    "count_words",
    "detect_ocr_engines",
    "parse_pages_string",
    "run_compare",
    "slice_pdf_to_tmpfile",
]


logger = get_logger(__name__)


MotorStatus = Literal["ok", "skipped", "error"]


@dataclass(frozen=True)
class MotorResult:
    """Resultado de un motor individual en el comparador."""

    name: str
    words: int
    headings: int
    time_seconds: float
    status: MotorStatus
    error: str | None = None


@dataclass(frozen=True)
class CompareReport:
    """Reporte agregado del comparador de motores (K5)."""

    source: Path
    pages: str | None
    elapsed_seconds: float
    motors: tuple[MotorResult, ...] = field(default_factory=tuple)

    @property
    def ok_motors(self) -> tuple[MotorResult, ...]:
        return tuple(m for m in self.motors if m.status == "ok")


# ---------------------------------------------------------------------------
# Page range parsing
# ---------------------------------------------------------------------------


_PAGE_RANGE_RE = re.compile(
    r"^\s*\d+\s*(?:-\s*\d+\s*)?"
    r"(?:\s*,\s*\d+\s*(?:-\s*\d+\s*)?)*\s*$"
)


def parse_pages_string(s: str | None) -> list[int] | None:
    """Parsea un string tipo ``"45-50"`` / ``"1-3,7,10-12"`` → ``[45,46,...,50]``.

    Devuelve ``None`` si ``s`` es None o vacío (significa "todo el PDF").
    Levanta :class:`ValueError` si el formato es inválido.
    """
    if not s or not s.strip():
        return None
    if not _PAGE_RANGE_RE.match(s):
        raise ValueError(f"page range inválido: {s!r}")
    pages: list[int] = []
    for piece in s.split(","):
        piece = piece.strip()
        if "-" in piece:
            start_s, end_s = piece.split("-", 1)
            start = int(start_s.strip())
            end = int(end_s.strip())
            if start < 1 or end < start:
                raise ValueError(f"range inválido: {piece!r}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(piece))
    return pages


# ---------------------------------------------------------------------------
# PDF slicing
# ---------------------------------------------------------------------------


def slice_pdf_to_tmpfile(
    pdf_bytes: bytes,
    pages: list[int] | None,
    tmpdir: Path,
) -> Path:
    """Extrae un subset de páginas del PDF y lo escribe en ``tmpdir``.

    Si ``pages`` es ``None``, copia el PDF completo. El path resultante
    se devuelve para que los motores lo lean.
    """
    if pages is None:
        out_path = tmpdir / "source.pdf"
        out_path.write_bytes(pdf_bytes)
        return out_path

    src_doc = pdfium.PdfDocument(pdf_bytes)
    if max(pages) > len(src_doc):
        raise ValueError(
            f"page range excede el largo del PDF: "
            f"solicitado max={max(pages)}, pdf tiene {len(src_doc)} páginas"
        )

    new_doc = pdfium.PdfDocument.new()
    # pypdfium2 0.x usa 0-based pages indices.
    new_doc.import_pages(src_doc, [p - 1 for p in pages])
    out_path = tmpdir / "subset.pdf"
    new_doc.save(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def count_words(text: str) -> int:
    """Cuenta palabras (split por whitespace).

    Más simple que contar tokens NLP: el comparador solo necesita una
    métrica relativa para ver "qué tanto markdown crudo extrajo cada
    motor", no para análisis lingüístico.
    """
    return len(text.split())


def count_headings(text: str) -> int:
    """Cuenta headings markdown (líneas que arrancan con ``#`` a ``######``).

    Ignora hashes inline (`text with #hash inline` → 0).
    """
    return len(re.findall(r"^#{1,6} ", text, re.MULTILINE))


# ---------------------------------------------------------------------------
# Motor detection
# ---------------------------------------------------------------------------


def detect_ocr_engines() -> tuple[str, ...]:
    """Devuelve los nombres de motores OCR disponibles.

    Cada motor requiere el binario externo en PATH:

    - ``tesseract``: el motor de OCR de Google (brew/apt install tesseract).
    - ``ocrmypdf``: wrapper Python sobre tesseract que preserva el texto
      embebido del PDF + agrega una capa OCR (pip install ocrmypdf).

    Devuelve tupla vacía si ninguno está instalado. El compare los
    usa como "skipped (binario no instalado)" cuando aplique.
    """
    found: list[str] = []
    if shutil.which("tesseract") is not None:
        found.append("ocr-tesseract")
    if shutil.which("ocrmypdf") is not None:
        found.append("ocr-ocrmypdf")
    return tuple(found)


def _is_cu_available() -> bool:
    return bool(os.environ.get("MARKITDOWN_CU_ENDPOINT"))


def _is_docintel_available() -> bool:
    return bool(os.environ.get("MARKITDOWN_DOCINTEL_ENDPOINT"))


# ---------------------------------------------------------------------------
# Motor runners (todos sin raise)
# ---------------------------------------------------------------------------


def _run_builtin_motor(
    pdf_path: Path,
    timeout: int,
) -> MotorResult:
    """Motor built-in: ``Engine.convert_path`` sobre el PDF."""
    name = "built-in"
    start = time.perf_counter()
    try:
        from capmd.convert.engine import Engine
        from capmd.convert.limits import ConversionLimits

        engine = Engine(
            limits=ConversionLimits(timeout_seconds=timeout),
        )
        result = engine.convert_path(pdf_path)
        elapsed = time.perf_counter() - start
        return MotorResult(
            name=name,
            words=count_words(result.markdown),
            headings=count_headings(result.markdown),
            time_seconds=elapsed,
            status="ok",
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.warning("built-in motor failed: %s", exc)
        return MotorResult(
            name=name,
            words=0,
            headings=0,
            time_seconds=elapsed,
            status="error",
            error=str(exc),
        )


def _run_docintel_motor(
    pdf_path: Path,
    timeout: int,
) -> MotorResult:
    """Motor Doc Intel: subprocess a markitdown con -d -e (vía K4)."""
    name = "docintel"
    start = time.perf_counter()
    try:
        from tempfile import TemporaryDirectory

        from capmd.convert.azure import (
            AzureRouting,
            build_markitdown_argv,
            run_markitdown_subprocess,
        )

        endpoint = os.environ.get("MARKITDOWN_DOCINTEL_ENDPOINT")
        routing = AzureRouting(
            use_docintel=True,
            docintel_endpoint=endpoint,
            timeout_seconds=timeout,
        )
        with TemporaryDirectory() as tmpdir:
            tmp_md = Path(tmpdir) / "out.md"
            build_markitdown_argv(str(pdf_path), str(tmp_md), routing)
            run_markitdown_subprocess(
                input_path=str(pdf_path),
                output_path=str(tmp_md),
                routing=routing,
            )
            markdown = tmp_md.read_text(encoding="utf-8")

        elapsed = time.perf_counter() - start
        return MotorResult(
            name=name,
            words=count_words(markdown),
            headings=count_headings(markdown),
            time_seconds=elapsed,
            status="ok",
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.warning("docintel motor failed: %s", exc)
        return MotorResult(
            name=name,
            words=0,
            headings=0,
            time_seconds=elapsed,
            status="error",
            error=str(exc),
        )


def _run_cu_motor(
    pdf_path: Path,
    timeout: int,
) -> MotorResult:
    """Motor CU: subprocess a markitdown con --use-cu (vía K4)."""
    name = "content-understanding"
    start = time.perf_counter()
    try:
        from tempfile import TemporaryDirectory

        from capmd.convert.azure import (
            AzureRouting,
            run_markitdown_subprocess,
        )

        endpoint = os.environ.get("MARKITDOWN_CU_ENDPOINT")
        routing = AzureRouting(
            use_cu=True,
            cu_endpoint=endpoint,
            timeout_seconds=timeout,
        )
        with TemporaryDirectory() as tmpdir:
            tmp_md = Path(tmpdir) / "out.md"
            run_markitdown_subprocess(
                input_path=str(pdf_path),
                output_path=str(tmp_md),
                routing=routing,
            )
            markdown = tmp_md.read_text(encoding="utf-8")

        elapsed = time.perf_counter() - start
        return MotorResult(
            name=name,
            words=count_words(markdown),
            headings=count_headings(markdown),
            time_seconds=elapsed,
            status="ok",
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.warning("cu motor failed: %s", exc)
        return MotorResult(
            name=name,
            words=0,
            headings=0,
            time_seconds=elapsed,
            status="error",
            error=str(exc),
        )


def _run_tesseract_motor(
    pdf_path: Path,
    timeout: int,
) -> MotorResult:
    """Motor OCR tesseract: renderiza pages a PNG y pipea a tesseract.

    Solo se invoca si ``tesseract`` está en PATH (decisión del caller).
    """
    name = "ocr-tesseract"
    start = time.perf_counter()
    try:

        # Renderizar las páginas del PDF a PNG.
        doc = pdfium.PdfDocument(str(pdf_path))
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            ocr_chunks: list[str] = []
            for i, page in enumerate(doc, start=1):
                pil_image = page.render(scale=2.0).to_pil()
                png_path = tmp / f"page-{i}.png"
                pil_image.save(png_path)
                proc = subprocess.run(
                    ["tesseract", str(png_path), "stdout", "-l", "spa+eng"],
                    timeout=timeout,
                    capture_output=True,
                    text=True,
                )
                text = proc.stdout.strip()
                if text:
                    ocr_chunks.append(f"# Page {i}\n\n{text}\n")
            markdown = "\n".join(ocr_chunks)

        elapsed = time.perf_counter() - start
        return MotorResult(
            name=name,
            words=count_words(markdown),
            headings=count_headings(markdown),
            time_seconds=elapsed,
            status="ok",
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.warning("ocr-tesseract motor failed: %s", exc)
        return MotorResult(
            name=name,
            words=0,
            headings=0,
            time_seconds=elapsed,
            status="error",
            error=str(exc),
        )


def _run_ocrmypdf_motor(
    pdf_path: Path,
    timeout: int,
) -> MotorResult:
    """Motor OCR ocrmypdf: ``ocrmypdf input.pdf output.pdf`` + built-in.

    Solo se invoca si ``ocrmypdf`` está en PATH. La ventaja de ocrmypdf
    sobre tesseract directo: preserva el texto embebido del PDF cuando
    existe y agrega una capa OCR limpia cuando no.
    """
    name = "ocr-ocrmypdf"
    start = time.perf_counter()
    try:
        from capmd.convert.engine import Engine
        from capmd.convert.limits import ConversionLimits

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            ocr_pdf = tmp / "ocr.pdf"
            proc = subprocess.run(
                ["ocrmypdf", "--skip-text", str(pdf_path), str(ocr_pdf)],
                timeout=timeout,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"ocrmypdf exit {proc.returncode}: "
                    f"{_truncate(proc.stderr)}"
                )

            limits = ConversionLimits(timeout_seconds=timeout)
            engine = Engine(limits=limits)
            result = engine.convert_path(ocr_pdf)
            markdown = result.markdown

        elapsed = time.perf_counter() - start
        return MotorResult(
            name=name,
            words=count_words(markdown),
            headings=count_headings(markdown),
            time_seconds=elapsed,
            status="ok",
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.warning("ocr-ocrmypdf motor failed: %s", exc)
        return MotorResult(
            name=name,
            words=0,
            headings=0,
            time_seconds=elapsed,
            status="error",
            error=str(exc),
        )


def _truncate(text: str, max_lines: int = 5) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[-max_lines:])


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_compare(
    *,
    source: Path,
    pages: str | None = None,
    timeout: int = 600,
    requested_ocr_engine: str | None = None,
    enable_cu: bool = True,
) -> CompareReport:
    """Corre todos los motores disponibles y devuelve el :class:`CompareReport`.

    Decisiones:
    - ``built-in`` siempre corre (es el motor por defecto).
    - Si ``enable_cu=True`` y ``MARKITDOWN_CU_ENDPOINT`` está seteada,
      corre ``content-understanding``.
    - Si ``enable_cu=True`` y ``MARKITDOWN_DOCINTEL_ENDPOINT`` está
      seteada, corre ``docintel``.
    - Si ``detect_ocr_engines()`` devuelve motores y ``requested_ocr_engine``
      matchea (o es ``None`` para auto-detect), corre los OCR disponibles.

    Ningún motor aborta el compare: cada uno se ejecuta independiente
    y captura excepciones. Si menos de 2 motores completan con
    ``status="ok"``, el reporte lo refleja (el caller decide el exit code).
    """
    start = time.perf_counter()

    # 1. Leer el PDF y (si aplica) slicearlo.
    pdf_bytes = source.read_bytes()
    pages_list = parse_pages_string(pages)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_pdf = slice_pdf_to_tmpfile(pdf_bytes, pages_list, Path(tmpdir))

        # 2. Construir la lista de motores a correr.
        motor_runners: list[tuple[str, Any]] = [
            ("built-in", lambda: _run_builtin_motor(tmp_pdf, timeout)),
        ]
        if enable_cu:
            if _is_docintel_available():
                motor_runners.append(
                    ("docintel", lambda: _run_docintel_motor(tmp_pdf, timeout))
                )
            if _is_cu_available():
                motor_runners.append(
                    (
                        "content-understanding",
                        lambda: _run_cu_motor(tmp_pdf, timeout),
                    )
                )

        # OCR: si requested_ocr_engine es None, corren todos los
        # disponibles (tesseract + ocrmypdf). Si es uno específico,
        # solo ese. Los motores no disponibles se reportan como
        # "skipped" al final (no se excluyen del reporte).
        ocr_choices = ("tesseract", "ocrmypdf")
        for ocr in ocr_choices:
            if (
                requested_ocr_engine is None
                or requested_ocr_engine == ocr
            ):
                ocr_name = f"ocr-{ocr}"
                if shutil.which(ocr) is not None:
                    if ocr == "tesseract":
                        motor_runners.append(
                            (ocr_name, lambda: _run_tesseract_motor(tmp_pdf, timeout))
                        )
                    elif ocr == "ocrmypdf":
                        motor_runners.append(
                            (ocr_name, lambda: _run_ocrmypdf_motor(tmp_pdf, timeout))
                        )
                else:
                    # Skipped: motor conocido pero binario no en PATH.
                    # Capturamos ``ocr_name`` como default del lambda
                    # para evitar que Python reuse la referencia y todas
                    # las lambdas terminen apuntando al último ``ocr``
                    # del loop.
                    motor_runners.append(
                        (
                            ocr_name,
                            lambda name=ocr_name, ocr_bin=ocr: MotorResult(
                                name=name,
                                words=0,
                                headings=0,
                                time_seconds=0.0,
                                status="skipped",
                                error=f"{ocr_bin} not installed",
                            ),
                        )
                    )

        # 3. Correr todos los motores. Si uno falla, su propio MotorResult
        # captura el error y devuelve status="error".
        results: list[MotorResult] = []
        for _name, runner in motor_runners:
            try:
                results.append(runner())
            except Exception as exc:
                # Defense in depth: el runner no debería propagar, pero
                # si lo hace, no abortamos el compare.
                logger.warning(
                    "motor runner raised unexpectedly: %s", exc
                )
                results.append(
                    MotorResult(
                        name="<unknown>",
                        words=0,
                        headings=0,
                        time_seconds=0.0,
                        status="error",
                        error=str(exc),
                    )
                )

    elapsed = time.perf_counter() - start
    return CompareReport(
        source=source,
        pages=pages,
        elapsed_seconds=elapsed,
        motors=tuple(results),
    )
