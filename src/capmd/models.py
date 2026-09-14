"""Dataclasses del dominio de capmd.

Todas son frozen (value objects). El parsing de sintaxis CLI (`45-78`,
`12,15,20-25`, etc.) es responsabilidad de C4, no de A5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Format = Literal["pdf", "epub", "docx", "pptx", "xlsx", "other"]

__all__ = [
    "Chapter",
    "ConversionOutput",
    "ConversionResult",
    "Figure",
    "Format",
    "PageRange",
    "QualityReport",
    "SourceDoc",
]


@dataclass(frozen=True)
class SourceDoc:
    """Documento de entrada."""

    path: Path
    format: Format
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes must be >= 0, got {self.size_bytes}")
        if len(self.sha256) != 64:
            raise ValueError(f"sha256 must be 64 hex chars, got {len(self.sha256)}")


@dataclass(frozen=True)
class PageRange:
    """Set de páginas normalizado (1-indexed, ordenado, único)."""

    pages: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.pages:
            raise ValueError("PageRange.pages cannot be empty")
        for p in self.pages:
            if not isinstance(p, int) or isinstance(p, bool) or p < 1:
                raise ValueError(f"page numbers must be ints >= 1, got {p!r}")
        if list(self.pages) != sorted(set(self.pages)):
            raise ValueError("pages must be sorted and unique")

    def __contains__(self, page: int) -> bool:
        return page in self.pages

    def __len__(self) -> int:
        return len(self.pages)

    def __bool__(self) -> bool:
        return True


@dataclass(frozen=True)
class Chapter:
    """Entrada del outline del PDF."""

    title: str
    level: int
    start_page: int
    end_page: int
    index: int

    def __post_init__(self) -> None:
        if self.level < 1:
            raise ValueError(f"level must be >= 1, got {self.level}")
        if self.index < 1:
            raise ValueError(f"index must be >= 1, got {self.index}")
        if self.start_page < 1:
            raise ValueError(f"start_page must be >= 1, got {self.start_page}")
        if self.end_page < self.start_page:
            raise ValueError(
                f"end_page ({self.end_page}) must be >= start_page ({self.start_page})"
            )

    @property
    def end_page_inclusive(self) -> int:
        """Última página del capítulo (display)."""
        return self.end_page - 1


@dataclass(frozen=True)
class Figure:
    """Imagen extraída de un documento."""

    chapter_index: int
    index: int
    path: Path
    page: int
    bbox: tuple[float, float, float, float] | None = None
    caption: str | None = None
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if self.chapter_index < 1:
            raise ValueError(f"chapter_index must be >= 1, got {self.chapter_index}")
        if self.index < 1:
            raise ValueError(f"index must be >= 1, got {self.index}")
        if self.page < 1:
            raise ValueError(f"page must be >= 1, got {self.page}")
        if self.width is not None and self.width <= 0:
            raise ValueError(f"width must be > 0, got {self.width}")
        if self.height is not None and self.height <= 0:
            raise ValueError(f"height must be > 0, got {self.height}")
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError(f"bbox must have 4 floats, got {len(self.bbox)}")


@dataclass(frozen=True)
class QualityReport:
    """Stats y warnings de una corrida."""

    pages_processed: int
    word_count: int
    headings_detected: int
    figures_extracted: int
    warnings: tuple[str, ...] = ()
    cleaner_stats: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "pages_processed",
            "word_count",
            "headings_detected",
            "figures_extracted",
        ):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")


@dataclass(frozen=True)
class ConversionResult:
    """Salida completa de una conversión."""

    source: SourceDoc
    markdown: str
    figures: tuple[Figure, ...]
    report: QualityReport
    cleaners_applied: tuple[str, ...]
    range: PageRange | None = None
    chapter: Chapter | None = None


@dataclass(frozen=True)
class ConversionOutput:
    """Resultado de bajo nivel de :class:`Engine` para una corrida B5.

    Es la unidad mínima que ``Engine.convert_path`` /
    ``Engine.convert_stream`` devuelven: el markdown crudo, el tiempo que
    tardó y, cuando aplica, el tamaño y la cantidad de páginas del input.
    Los campos ``page_count`` y ``size_bytes`` son ``None`` para streams
    sin noción previa de tamaño (stdin).

    ``ConversionResult`` es un nivel más alto, pensado para el output
    final con quality report y figuras; se compone aguas arriba.
    """

    markdown: str
    elapsed_seconds: float
    page_count: int | None = None
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.elapsed_seconds < 0:
            raise ValueError(f"elapsed_seconds must be >= 0, got {self.elapsed_seconds}")
        if self.page_count is not None and self.page_count < 1:
            raise ValueError(f"page_count must be >= 1, got {self.page_count}")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError(f"size_bytes must be >= 0, got {self.size_bytes}")
