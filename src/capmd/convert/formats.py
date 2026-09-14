"""Tabla de formatos soportados y sentinel de extras de markitdown.

Cada ``FormatInfo`` describe un formato que capmd sabe convertir. El
``sentinel`` es el módulo que el extra de markitdown correspondiente
instala; lo usamos con ``importlib.util.find_spec`` para validar el
extra **sin importarlo** (cumple el "import lazy" del roadmap B2).

El formato ``.epub`` no requiere extra propio: usa ``zipfile`` y
``defusedxml``, ambos parte de las deps base de markitdown. Por eso su
``extra`` es ``None`` y su ``sentinel`` es ``""`` — se considera
siempre disponible.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatInfo:
    """Descripción inmutable de un formato soportado."""

    extension: str
    name: str
    extra: str | None
    sentinel: str

    def install_hint(self) -> str:
        """Mensaje humano indicando cómo instalar el extra, si aplica."""
        if self.extra is None:
            return f"{self.name} no requiere instalación adicional."
        return f"falta `pip install 'markitdown[{self.extra}]'`."


SUPPORTED_FORMATS: dict[str, FormatInfo] = {
    ".pdf": FormatInfo(".pdf", "PDF", "pdf", "pdfminer.high_level"),
    ".epub": FormatInfo(".epub", "EPUB", None, ""),
    ".docx": FormatInfo(".docx", "DOCX", "docx", "mammoth"),
    ".pptx": FormatInfo(".pptx", "PPTX", "pptx", "pptx"),
    ".xlsx": FormatInfo(".xlsx", "XLSX", "xlsx", "openpyxl"),
    # HTML/XHTML es interno: lo usa el slice de capítulos EPUB (C9)
    # para convertir el XHTML extraído. No es un formato de entrada
    # público: si el usuario pasa un .html directo a `capmd convert`,
    # igual funciona.
    ".html": FormatInfo(".html", "HTML", None, ""),
}


def known_extensions() -> list[str]:
    """Extensiones soportadas sin punto inicial, ordenadas alfabéticamente."""
    return sorted(ext.lstrip(".") for ext in SUPPORTED_FORMATS)
