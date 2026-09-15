"""Split por secciones H2 (F4).

A partir del markdown final (post-F2/F3) genera un árbol ``sections/``
con un archivo por cada ``##`` detectado:

    sections/
        00-intro.md                # contenido previo al primer ## (si no vacío)
        01-introduction.md
        02-borrowing.md
        …
        index.md                   # lista de links a cada sección

Funciones puras (sin I/O). El writer/orquestador se encarga de persistir.

Límites respetados:
- ``##`` dentro de code fences (```` ``` ```` o `~~~`) no se cuenta.
- ``##`` dentro de un front matter inicial no se cuenta (F2 ya lo prepende;
  este módulo lo strippea antes de splitear).
- ``#hashtag`` (sin espacio) no se cuenta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from capmd.clean._fences import split_outside_fences
from capmd.output.frontmatter import strip_existing_front_matter
from capmd.output.writer import slugify

__all__ = [
    "Section",
    "SectionSlice",
    "build_index_markdown",
    "extract_h2_sections",
    "section_filename",
    "split_section_filenames",
]


_H2_LINE_RE = re.compile(r"(?m)^## ([^\n]+?)\s*$")
_H1_LEADING_RE = re.compile(r"(?m)^\s*# [^\n]+?\s*\n+")


@dataclass(frozen=True)
class Section:
    """Una sección detectada por ``extract_h2_sections``."""

    title: str
    body: str  # markdown desde el H2 (excluido) hasta el próximo H2 o el final
    index: int  # 1-based (index de sección, no de archivo)


@dataclass(frozen=True)
class SectionSlice:
    """Resultado de partir un markdown en secciones H2."""

    prelude: str  # contenido antes del primer H2 (puede ser "")
    sections: tuple[Section, ...]  # 0+ secciones en orden


def extract_h2_sections(markdown: str) -> SectionSlice:
    """Parte ``markdown`` en un preludio y N secciones detectadas por H2.

    Pipeline:
      1. ``strip_existing_front_matter`` para ignorar ``##`` del YAML.
      2. ``split_outside_fences`` para no contar ``##`` dentro de code blocks.
      3. En cada segmento ``in_fence=False`` se buscan las líneas ``## …``.
      4. Se arma el preludio (todo antes del primer H2) y las secciones
         (desde cada H2 hasta el siguiente H2 o el final del doc).
      5. La 1-indexing de ``Section.index`` arranca en 1 en el primer H2
         encontrado (no en el preludio).

    ``## Palabrafalsa`` (sin espacio) no matchea — solo ``## texto``.
    """
    if not markdown:
        return SectionSlice(prelude="", sections=())

    without_fm = strip_existing_front_matter(markdown)

    # Texto fuera de fences donde buscar H2.
    outside_text_parts: list[str] = []
    for segment, in_fence in split_outside_fences(without_fm):
        if not in_fence:
            outside_text_parts.append(segment)
    outside_text = "".join(outside_text_parts)

    # Strip de un H1 inicial (representa el título del chapter; ya va
    # al FM del chapter .md y al index.md, no es contenido de sección).
    stripped_text = _H1_LEADING_RE.sub("", outside_text, count=1)

    # Encontrar (offset, title) de cada H2.
    matches = list(_H2_LINE_RE.finditer(stripped_text))
    if not matches:
        return SectionSlice(prelude=stripped_text, sections=())

    # Construir preludio + secciones.
    first_h2 = matches[0]
    # El preludio incluye el contenido hasta el inicio del primer H2;
    # NO se hace rstrip agresivo porque preserva el límite visual con
    # el primer heading (un solo ``\n`` separador es lo habitual).
    prelude = stripped_text[: first_h2.start()]
    sections: list[Section] = []
    for i, m in enumerate(matches):
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped_text)
        body = stripped_text[body_start:body_end]
        sections.append(
            Section(title=m.group(1).strip(), body=body, index=i + 1)
        )

    return SectionSlice(prelude=prelude, sections=tuple(sections))


def _zero_pad(total: int) -> int:
    """Ancho del zero-padding: 2 dígitos hasta 99, 3 desde 100."""
    return max(2, len(str(total)))


def section_filename(index: int, total: int, title: str) -> str:
    """Devuelve el nombre ``<index:0Nd>-<slug>.md`` para una sección.

    Sufijo numérico (``-2``, ``-3``…) si el slug colisiona con uno previo.
    Si el título slugea a ``""`` (solo símbolos), ``slugify`` retorna
    ``"untitled"``; aquí lo tratamos como ``"section"``.
    """
    pad = _zero_pad(total)
    slug = slugify(title, max_length=50)
    if not slug or slug == "untitled":
        slug = "section"
    return f"{index:0{pad}d}-{slug}.md"


def split_section_filenames(
    sections: tuple[Section, ...],
    *,
    has_prelude: bool,
) -> tuple[list[str], str | None]:
    """Calcula los filenames de cada sección y del intro.

    Returns
    -------
    tuple[list[str], str | None]
        ``(section_filenames, intro_filename_or_None)``. El intro
        filename es ``"00-intro.md"`` (con el mismo zero-pad de las
        secciones) solo si ``has_prelude`` es True.
    """
    total = max(len(sections), 1 if has_prelude else 0)
    pad = _zero_pad(total + (1 if has_prelude else 0))
    intro_idx = 0  # zero-padded intro

    used_slugs: dict[str, int] = {}
    result: list[str] = []

    for section in sections:
        slug = slugify(section.title, max_length=50)
        if not slug or slug == "untitled":
            slug = "section"
        seen = used_slugs.get(slug, 0)
        if seen == 0:
            used_slugs[slug] = 1
            filename = f"{section.index:0{pad}d}-{slug}.md"
        else:
            used_slugs[slug] = seen + 1
            filename = f"{section.index:0{pad}d}-{slug}-{seen + 1}.md"
        result.append(filename)

    intro_filename = f"{intro_idx:0{pad}d}-intro.md" if has_prelude else None
    return result, intro_filename


def build_index_markdown(
    chapter_title: str,
    sections: tuple[Section, ...],
    filenames: list[str],
    *,
    intro_filename: str | None,
) -> str:
    """Arma el contenido del ``index.md`` (sin front matter).

    Estructura::

        # <chapter_title>

        - [<section 1 title>](<section 1 filename>)
        - [<section 2 title>](<section 2 filename>)
        - …
        - [<intro title>](00-intro.md)

    ``chapter_title`` puede ser ``""`` (no se imprime H1 en ese caso).
    """
    lines: list[str] = []
    if chapter_title:
        lines.append(f"# {chapter_title}\n")

    # El intro va al final de la lista (es el "preludio", posterior lógicamente
    # a las secciones principales).
    pairs = list(zip(sections, filenames, strict=True))
    if intro_filename is not None:
        pairs.append((Section(title="Prelude", body="", index=0), intro_filename))

    for section, filename in pairs:
        # Escapar ``[`` / ``]`` en títulos para no romper la sintaxis de link.
        title_escaped = section.title.replace("[", "\\[").replace("]", "\\]")
        lines.append(f"- [{title_escaped}]({filename})")
    body = "\n".join(lines) + "\n"
    return body
