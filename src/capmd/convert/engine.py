"""Wrapper sobre :class:`markitdown.MarkItDown`.

La clase :class:`Engine` aísla a capmd de la API de markitdown:
instancia ``MarkItDown`` una sola vez y expone una superficie mínima
(``convert_path``, ``convert_stream``). Solo usa ``convert_local`` /
``convert_stream`` — nunca ``convert`` — porque la API ancha de
``convert`` admite URLs y puede terminar descargando recursos
remotos, que no es lo que queremos.

Los métodos devuelven :class:`capmd.models.ConversionOutput` para
reportar tiempo, tamaño y páginas al caller (B5).
"""

from __future__ import annotations

import importlib.util
import io
import signal
import time
from pathlib import Path
from typing import Any, BinaryIO

from markitdown import MarkItDown, StreamInfo

from capmd.convert.formats import (
    SUPPORTED_FORMATS,
    FormatInfo,
    known_extensions,
)
from capmd.convert.limits import DEFAULT_LIMITS, ConversionLimits
from capmd.errors import (
    ConversionFailed,
    InputTooLarge,
    SourceNotFound,
    UnsupportedFormat,
)
from capmd.logging import get_logger
from capmd.models import ConversionOutput

logger = get_logger(__name__)


def _normalize_extension(extension: str) -> str:
    """Devuelve la extensión con punto inicial y en minúsculas.

    Acepta ``"pdf"``, ``".pdf"``, ``"PDF"``. Cualquier otra cosa
    (espacios, barras, vacío) se devuelve tal cual para que el lookup
    en :data:`SUPPORTED_FORMATS` falle limpiamente.
    """
    ext = extension.strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return ext


class Engine:
    """Adaptador estable sobre :class:`markitdown.MarkItDown`.

    Parameters
    ----------
    enable_plugins:
        Pasa a ``MarkItDown(enable_plugins=...)``. Default ``False``.
        B1 no necesita plugins; E6 los activa cuando hay ``llm_client``.
    limits:
        :class:`ConversionLimits` a aplicar a cada conversión. Si es
        ``None``, se usan los defaults de B5 (500 MB / 5000 páginas /
        600 s / aviso a 500 páginas).
    llm_client:
        Cliente LLM para describir imágenes (E6). Si se setea,
        ``enable_plugins`` se fuerza a ``True`` automáticamente porque
        ``markitdown-ocr`` requiere plugins activos. Si es ``None``,
        no se hace descripción de imágenes vía LLM.
    llm_model:
        Modelo a usar con ``llm_client`` (E6). Si es ``None`` y hay
        ``llm_client``, se usa el default del proveedor
        (configurado en :mod:`capmd.llm`).
    """

    def __init__(
        self,
        *,
        enable_plugins: bool = False,
        limits: ConversionLimits | None = None,
        llm_client: Any = None,
        llm_model: str | None = None,
    ) -> None:
        # Forzar plugins activos cuando hay cliente LLM.
        plugins = enable_plugins or llm_client is not None
        self._md = MarkItDown(
            enable_plugins=plugins,
            llm_client=llm_client,
            llm_model=llm_model,
        )
        self._limits = limits if limits is not None else DEFAULT_LIMITS
        self._llm_client = llm_client
        self._llm_model = llm_model
        self._plugins = plugins

    @property
    def llm_enabled(self) -> bool:
        """True si el Engine tiene un cliente LLM configurado (E6)."""
        return self._llm_client is not None

    def supported_formats(self) -> list[str]:
        """Extensiones soportadas (sin punto, ordenadas). Para help y mensajes."""
        return known_extensions()

    @property
    def limits(self) -> ConversionLimits:
        """Límites efectivos del engine (B5)."""
        return self._limits  # pragma: no cover

    def check_supported(self, path: Path) -> FormatInfo:
        """Valida que ``path`` sea convertible por capmd.

        Devuelve el :class:`FormatInfo` correspondiente. Levanta
        :class:`UnsupportedFormat` si la extensión no está registrada
        o si el extra de markitdown para esa extensión no está
        instalado (chequeo lazy vía ``importlib.util.find_spec``).
        """
        info = _resolve_format(path.suffix.lower())
        if info is None:
            ext = path.suffix.lower().lstrip(".") or "<sin extensión>"
            raise UnsupportedFormat(
                f"formato no soportado: {ext!r} ({path.name})",
                hint=f"formatos soportados: {', '.join(self.supported_formats())}",
            )
        _check_extra_installed(info, source_name=path.name)
        return info

    def convert_path(
        self,
        path: Path,
        *,
        limits: ConversionLimits | None = None,
    ) -> ConversionOutput:
        """Convierte un archivo local a Markdown.

        Antes de llamar a markitdown aplica los chequeos de tamaño y
        cantidad de páginas (``InputTooLarge``, exit 6). Mide el tiempo
        de la conversión y (en POSIX) la aborta con ``signal.alarm``
        si supera ``timeout_seconds``.

        Devuelve un :class:`ConversionOutput` con el markdown, el
        tiempo transcurrido, la cantidad de páginas (solo PDF) y el
        tamaño del archivo en bytes.
        """
        effective = limits or self._limits
        if not path.exists() or not path.is_file():
            raise SourceNotFound(
                f"no se encontró el archivo: {path}",
                hint="verificá la ruta o pasá el archivo por stdin con --ext",
            )
        info = self.check_supported(path)
        size_bytes = path.stat().st_size
        _check_size_limit(size_bytes, effective, source=path.name)
        page_count = _count_pdf_pages(path) if info.extension == ".pdf" else None
        _check_page_count_limit(page_count, effective, source=path.name)
        _maybe_warn_large_pdf(page_count, effective)
        logger.debug("convirtiendo %s como %s", path, info.name)

        start = time.perf_counter()
        text = _run_with_timeout(
            lambda: self._md.convert_local(str(path)),
            timeout_seconds=effective.timeout_seconds,
            failure_label=f"markitdown ({path.name})",
        )
        elapsed = time.perf_counter() - start
        markdown = _extract_markdown(text)
        logger.debug("ok %d chars en %.3fs", len(markdown), elapsed)
        return ConversionOutput(
            markdown=markdown,
            elapsed_seconds=elapsed,
            page_count=page_count,
            size_bytes=size_bytes,
        )

    def convert_stream(
        self,
        stream: BinaryIO,
        *,
        extension: str,
        limits: ConversionLimits | None = None,
    ) -> ConversionOutput:
        """Convierte bytes crudos de un stream a Markdown.

        Equivalente a :meth:`convert_path` pero leyendo de un stream
        binario (típicamente ``sys.stdin.buffer``). Como no conocemos
        el tamaño total ni la cantidad de páginas, ``size_bytes`` y
        ``page_count`` en el resultado son ``None``. El ``--timeout``
        sí se aplica.
        """
        effective = limits or self._limits
        info = _resolve_format(_normalize_extension(extension))
        if info is None:
            ext = _normalize_extension(extension).lstrip(".") or "<vacío>"
            raise UnsupportedFormat(
                f"formato no soportado: {ext!r} (stdin)",
                hint=f"formatos soportados: {', '.join(self.supported_formats())}",
            )
        _check_extra_installed(info, source_name="stdin")
        logger.debug("convirtiendo stdin como %s", info.name)

        stream_info = StreamInfo(extension=info.extension)
        start = time.perf_counter()
        result = _run_with_timeout(
            lambda: self._md.convert_stream(stream, stream_info=stream_info),
            timeout_seconds=effective.timeout_seconds,
            failure_label="markitdown (stdin)",
        )
        elapsed = time.perf_counter() - start
        markdown = _extract_markdown(result)
        logger.debug("ok %d chars en %.3fs", len(markdown), elapsed)
        return ConversionOutput(
            markdown=markdown,
            elapsed_seconds=elapsed,
            page_count=None,
            size_bytes=None,
        )

    def convert_pages(
        self,
        path: Path,
        *,
        limits: ConversionLimits | None = None,
    ) -> list[str]:
        """Convierte cada página del PDF por separado.

        Solo PDF. Para otros formatos levanta :class:`UnsupportedFormat`.
        Devuelve una lista con N strings, uno por página (páginas vacías
        devuelven string vacío).
        """
        effective = limits or self._limits
        if not path.exists() or not path.is_file():
            raise SourceNotFound(
                f"no se encontró el archivo: {path}",
                hint="verificá la ruta o pasá el archivo por stdin con --ext",
            )
        info = self.check_supported(path)
        if info.extension != ".pdf":
            raise UnsupportedFormat(
                f"convert_pages solo aplica a PDF, no a {info.name}: {path.name}",
                hint="usá convert_path para una conversión sin markers",
            )

        size_bytes = path.stat().st_size
        _check_size_limit(size_bytes, effective, source=path.name)

        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:  # pragma: no cover
            raise UnsupportedFormat(  # pragma: no cover
                f"pypdf no instalado: no puedo convertir página por página ({path.name})",
                hint="pip install pypdf",
            ) from None

        reader = PdfReader(str(path))
        n_pages = len(reader.pages)
        _check_page_count_limit(n_pages, effective, source=path.name)
        _maybe_warn_large_pdf(n_pages, effective)

        logger.debug("convirtiendo %d páginas individualmente de %s", n_pages, path)
        pages: list[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)
            buf = io.BytesIO()
            writer.write(buf)
            buf.seek(0)
            try:
                result = _run_with_timeout(
                    lambda buf=buf: self._md.convert_stream(
                        buf, stream_info=StreamInfo(extension=".pdf")
                    ),
                    timeout_seconds=effective.timeout_seconds,
                    failure_label=f"markitdown page {idx} ({path.name})",
                )
            finally:
                buf.close()
            pages.append(_extract_markdown(result))
        logger.debug("ok %d páginas convertidas", len(pages))
        return pages


def _extract_markdown(result: Any) -> str:
    """Devuelve el texto markdown del resultado de markitdown.

    Prefiere ``result.markdown`` (API actual). Si no existe, cae a
    ``result.text_content`` (forks viejos). Por último, ``str(result)``
    como red de seguridad.
    """
    md = getattr(result, "markdown", None)
    if isinstance(md, str):
        return md
    legacy = getattr(result, "text_content", None)  # pragma: no cover
    if isinstance(legacy, str):  # pragma: no cover
        return legacy  # pragma: no cover
    return str(result)  # pragma: no cover


def _resolve_format(extension: str) -> FormatInfo | None:
    """Lookup directo en :data:`SUPPORTED_FORMATS`."""
    return SUPPORTED_FORMATS.get(extension)


def _check_extra_installed(info: FormatInfo, *, source_name: str) -> None:
    """Levanta :class:`UnsupportedFormat` si el extra de markitdown falta."""
    if info.sentinel and importlib.util.find_spec(info.sentinel) is None:
        raise UnsupportedFormat(
            f"falta el extra de markitdown para {info.name}: {source_name}",
            hint=info.install_hint(),
        )


def _check_size_limit(size_bytes: int, limits: ConversionLimits, *, source: str) -> None:
    """Levanta :class:`InputTooLarge` si el archivo supera ``max_size_bytes``."""
    if size_bytes > limits.max_size_bytes:
        actual_mb = size_bytes / 1_000_000
        cap_mb = limits.max_size_bytes / 1_000_000
        raise InputTooLarge(
            f"{actual_mb:.1f} MB supera el límite de {cap_mb:.0f} MB ({source})",
            hint="subí --max-size si el archivo es legítimo, o usá --pages para reducir el rango",
        )


def _check_page_count_limit(
    page_count: int | None, limits: ConversionLimits, *, source: str
) -> None:
    """Levanta :class:`InputTooLarge` si el PDF supera ``max_pages``."""
    if page_count is None:
        return
    if page_count > limits.max_pages:
        raise InputTooLarge(
            f"{page_count} páginas supera el límite de {limits.max_pages} ({source})",
            hint="subí --max-pages si el PDF es legítimo, o usá --pages para reducir el rango",
        )


def _maybe_warn_large_pdf(page_count: int | None, limits: ConversionLimits) -> None:
    """Loggea un warning si el PDF supera ``warn_pages`` (no bloquea)."""
    if page_count is None:
        return
    if page_count > limits.warn_pages:
        logger.warning(
            "PDF grande: %d páginas (umbral de aviso: %d)",
            page_count,
            limits.warn_pages,
        )


def _count_pdf_pages(path: Path) -> int | None:
    """Cuenta páginas de un PDF con pypdf.

    Lazy: importa pypdf solo si hace falta. Si falla (PDF corrupto,
    pypdf no instalado), devuelve ``None`` para no bloquear; el
    error real lo va a reportar markitdown al intentar convertir.
    """
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        logger.debug("pypdf no instalado: salteo conteo de páginas")  # pragma: no cover
        return None  # pragma: no cover
    try:
        return len(PdfReader(str(path)).pages)
    except Exception as exc:
        logger.debug("no pude contar páginas de %s: %s", path, exc)
        return None


def _run_with_timeout(fn: Any, *, timeout_seconds: int, failure_label: str) -> Any:
    """Ejecuta ``fn()`` con timeout duro via ``signal.alarm`` (POSIX).

    En Windows / sin ``signal.alarm`` solo mide y no enforce; el caller
    puede detectar el timeout mirando logs o el delta de tiempo.
    Devuelve el resultado de ``fn()`` o levanta
    :class:`ConversionFailed` con hint de timeout si dispara.
    """
    if not hasattr(signal, "SIGALRM"):
        logger.debug("signal.SIGALRM no disponible: timeout no se enforce")  # pragma: no cover
        return fn()  # pragma: no cover

    def _handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"{failure_label} excedió --timeout={timeout_seconds}s")

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_seconds)
    try:
        return fn()
    except TimeoutError as exc:
        raise ConversionFailed(
            f"timeout: {failure_label} excedió {timeout_seconds}s",
            hint="subí --timeout si la conversión es legítima, o convertí un sub-rango con --pages",
        ) from exc
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
