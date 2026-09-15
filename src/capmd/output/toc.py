"""Tabla de contenidos inline (F5).

Con ``--toc``, capmd inyecta una tabla de contenidos al inicio del
markdown final (después del primer H1, o al tope del body si no hay
H1). El rango de niveles es configurable vía ``--toc-depth N``
(default: H2 + H3). Cada link de la TOC apunta a un heading real del
documento.

Anclas estilo GitHub:

  - lowercase
  - solo ``[a-z0-9-]`` (Unicode letters se conservan literales)
  - runs de ``-`` colapsan a uno solo; trim en bordes
  - dedup con sufijos ``-1``, ``-2`` cuando hay colisión

Marcado idempotente: el bloque TOC va envuelto en sentinels
``<!-- capmd:toc:open -->`` / ``<!-- capmd:toc:close -->`` para que
``inject_toc`` reemplace un TOC previo en lugar de duplicarlo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from capmd.clean._fences import split_outside_fences
from capmd.output.frontmatter import strip_existing_front_matter

__all__ = [
    "TOC_SENTINEL_CLOSE",
    "TOC_SENTINEL_OPEN",
    "Heading",
    "build_toc_block",
    "extract_headings",
    "inject_toc",
    "markdown_anchor",
    "slugify_anchor",
]


TOC_SENTINEL_OPEN = "<!-- capmd:toc:open -->"
TOC_SENTINEL_CLOSE = "<!-- capmd:toc:close -->"

# ``(?m)^## ...$``. H1..H6 detectados con el mismo regex parametrizado.
_HEADING_RE = re.compile(r"(?m)^(#{1,6}) ([^\n]+?)\s*$")
_H1_LEADING_RE = re.compile(r"(?m)^\s*# [^\n]+?\s*\n+")

_ANCHOR_RUN_RE = re.compile(r"[^\w\-]+", re.UNICODE)
_ANCHOR_DASHES_RE = re.compile(r"-{2,}")


def _is_word_char(ch: str) -> bool:
    """Letra, dígito, ``_`` o ``-``. Usa ``unicodedata.category`` para
    conservar letras de cualquier script (CJK, cirílico, etc.)."""
    if ch in "-_":
        return True
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N")


@dataclass(frozen=True)
class Heading:
    """Un heading detectado para la TOC."""

    level: int        # 1..6
    title: str        # texto del heading
    anchor: str       # slug estilo GitHub


# --- Anchor ---------------------------------------------------------------


def markdown_anchor(title: str) -> str:
    """Devuelve el anchor estilo GitHub para ``title``.

    NFC normalization primero (forma compuesta, p.ej. ``á`` estable).
    Lowercase. Conserva letras Unicode (acentos, CJK, cirílico)
    literales via ``unicodedata.category``. Strip de puntuación que no
    sea ``-`` o ``_``. Colapsa runs de ``-``. Trim ``-`` y ``_`` en
    bordes. Si queda vacío, devuelve ``"untitled"``.
    """
    if not title:
        return "untitled"
    normalized = unicodedata.normalize("NFC", title)
    lowered = normalized.lower()
    chars: list[str] = []
    for ch in lowered:
        if _is_word_char(ch):
            chars.append(ch if ch != "_" else "_")
        else:
            chars.append("-")
    slug = "".join(chars).strip("-_")
    slug = _ANCHOR_DASHES_RE.sub("-", slug)
    return slug or "untitled"


def slugify_anchor(title: str, used: set[str]) -> str:
    """Igual a :func:`markdown_anchor` pero deduplica contra ``used``.

    Si el anchor ya está en uso, agrega ``-1``, ``-2``, etc.
    """
    base = markdown_anchor(title)
    candidate = base
    counter = 1
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate


# --- Headings extraction --------------------------------------------------


def extract_headings(
    markdown: str,
    *,
    min_level: int = 2,
    max_level: int = 3,
) -> list[Heading]:
    """Devuelve headings del markdown en rango ``min_level..max_level``.

    - Respeta code fences (`` ```` ``` ```` y ``~~~``).
    - Ignora headings vacíos (``# `` sin texto).
    - Ignora el H1 chapter-title si no entra en el rango (lo cual
      sucede siempre con el default ``min_level=2``).
    - Dedup de anchors vía :func:`slugify_anchor`.
    """
    if not markdown or max_level < min_level:
        return []

    without_fm = strip_existing_front_matter(markdown)

    # Texto fuera de fences.
    outside_parts: list[str] = []
    for segment, in_fence in split_outside_fences(without_fm):
        if not in_fence:
            outside_parts.append(segment)
    outside_text = "".join(outside_parts)

    used: set[str] = set()
    headings: list[Heading] = []
    for m in _HEADING_RE.finditer(outside_text):
        level = len(m.group(1))
        if level < min_level or level > max_level:
            continue
        title = m.group(2).strip()
        if not title:
            continue
        anchor = slugify_anchor(title, used)
        headings.append(Heading(level=level, title=title, anchor=anchor))
    return headings


# --- TOC rendering --------------------------------------------------------


def build_toc_block(headings: list[Heading]) -> str:
    """Renderiza la lista markdown de la TOC, envuelta en sentinels.

    Cada H2 (level 2) arranca sin indent; los siguientes niveles se
    indetan con ``2 * (level - 2)`` espacios. Los corchetes en el
    título se escapan (``\\``) para no romper la sintaxis del link
    markdown. Devuelve ``""`` si no hay headings.
    """
    if not headings:
        return ""
    lines: list[str] = []
    for h in headings:
        indent = " " * (2 * (h.level - 2))
        title_escaped = h.title.replace("[", "\\[").replace("]", "\\]")
        lines.append(f"{indent}- [{title_escaped}](#{h.anchor})")
    body = "\n".join(lines) + "\n"
    return f"{TOC_SENTINEL_OPEN}\n{body}{TOC_SENTINEL_CLOSE}\n"


# --- Strip existing + inject ----------------------------------------------


_TOC_SENTINELS_RE = re.compile(
    re.escape(TOC_SENTINEL_OPEN)
    + r".*?"
    + re.escape(TOC_SENTINEL_CLOSE)
    + r"\n?",
    re.DOTALL,
)


def strip_existing_toc(markdown: str) -> str:
    """Quita un bloque TOC previo (entre sentinels) del markdown."""
    return _TOC_SENTINELS_RE.sub("", markdown)


def inject_toc(markdown: str, *, depth: int = 3) -> str:
    """Devuelve ``markdown`` con un TOC inline insertado (F5).

    Comportamiento:
      - Strip del TOC previo (por sentinels, si lo hay).
      - Si no hay headings en rango ``[2, depth]``, devuelve el
        markdown sin cambios (con el previo ya strippeado).
      - Inserta el bloque TOC **después del primer H1** del markdown
        (convención GitHub). Si no hay H1, lo inserta al inicio.

    Parameters
    ----------
    markdown:
        Markdown limpio (post-pipeline). El bloque FM inicial (F2) no
        se ve afectado por :func:`strip_existing_front_matter` (que se
        llama internamente en :func:`extract_headings`); pero
        :func:`strip_existing_toc` debe correr sobre el markdown
        completo para que el sentinel previo se elimine aunque esté
        entre H1 y el primer H2.
    depth:
        Nivel máximo de headings a incluir (default 3 → H2 + H3).
    """
    cleaned = strip_existing_toc(markdown)
    headings = extract_headings(cleaned, min_level=2, max_level=depth)
    if not headings:
        return cleaned

    toc_block = build_toc_block(headings)

    # Buscar el final del primer H1 en el markdown CON FM (no queremos
    # meternos en el FM block; ``strip_existing_front_matter`` ya
    # garantiza que los sentinels no se cuentan). El offset se busca
    # en `cleaned` (post-strip-existing-toc) para mantener consistencia.
    h1_match = _H1_LEADING_RE.search(cleaned)
    if h1_match is None:
        # Sin H1: el TOC va al tope (después del FM si lo hay, antes
        # del primer contenido).
        without_fm = strip_existing_front_matter(cleaned)
        if not without_fm:
            return toc_block + cleaned
        # Encontrar el offset donde termina el FM block.
        from capmd.output.frontmatter import _FRONTMATTER_LEADING_RE
        fm_match = _FRONTMATTER_LEADING_RE.match(without_fm)
        if fm_match is None:
            return toc_block + "\n" + cleaned
        # Insertar justo después del FM + posibles newlines en limpio.
        fm_end = fm_match.end()
        # ``stripped`` no incluye ``leading_ws`` que ``cleaned`` podría
        # tener; usamos ``cleaned.find`` en su lugar.
        prefix_offset = cleaned.find(without_fm)
        insert_at = (prefix_offset if prefix_offset >= 0 else 0) + fm_end
        return cleaned[:insert_at] + toc_block + cleaned[insert_at:]

    insert_at = h1_match.end()
    return cleaned[:insert_at] + toc_block + cleaned[insert_at:]
