"""Front matter YAML al inicio del ``.md`` de salida (F2 + F3).

Cada archivo markdown que ``capmd`` escribe a disco arranca con un bloque
entre centinelas ``---`` con 10 claves::

    ---
    title: ...
    book: rust-handbook
    chapter: cap-03-ownership
    pages: [45, 46, 47]
    source_file: Rust Handbook.pdf
    source_sha256: abc...
    converted_at: 2026-09-15T00:00:00Z
    capmd_version: 0.1.0
    markitdown_version: 0.1.7
    cleaners_applied:
      - whitespace
      - hyphens
      - ...
    ---

Stdout NO lleva front matter (es pipe, no archivo).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import yaml

from capmd.output.writer import markitdown_version

__all__ = [
    "NEUTRAL_STUDY_KEYS",
    "build_front_matter_fields",
    "extract_first_h1",
    "front_matter_fields_from_capmd_json",
    "markitdown_version",
    "parse_front_matter",
    "prepend_front_matter",
    "render_front_matter",
    "strip_existing_front_matter",
]


_NEUTRAL_TAGS: tuple[str, ...] = ()
_NEUTRAL_STATUS = "unread"

NEUTRAL_STUDY_KEYS = (_NEUTRAL_TAGS, _NEUTRAL_STATUS, None, None)
"""Tupla ``(tags, reading_status, started_at, finished_at)`` que
representa el estado neutro del perfil study. Si ``build_front_matter_fields``
recibe exactamente estos valores, omite la sub-key ``study:`` del
dict resultante (compat con FMs pre-K2)."""


_FRONTMATTER_OPENING = "---"
_H1_RE = re.compile(r"(?m)^# ([^\n]+?)\s*$")
_FRONTMATTER_LEADING_RE = re.compile(
    r"^" + re.escape(_FRONTMATTER_OPENING) + r"\n.*?\n" + re.escape(_FRONTMATTER_OPENING) + r"[ \t]*\n+",
    re.DOTALL,
)

_FM_REQUIRED_KEYS = (
    "title", "book_slug", "chapter_slug", "pages", "source_file",
    "source_sha256", "generated_at", "capmd_version",
    "markitdown_version", "cleaners_applied",
)


def extract_first_h1(markdown: str) -> str | None:
    """Devuelve el texto del primer H1 (línea ``# Título``) o ``None``.

    Solo matchea un único ``#`` al inicio de línea seguido de espacio.
    ``##``, ``###`` y ``#palabra`` (sin espacio) no cuentan.
    Líneas en blanco antes del H1 se ignoran naturalmente — el regex
    usa ``re.MULTILINE`` con ``^`` que solo aplica al inicio de línea
    lógica.
    """
    m = _H1_RE.search(markdown)
    if m is None:
        return None
    return m.group(1)


def strip_existing_front_matter(markdown: str) -> str:
    """Quita un bloque front matter válido al inicio del markdown.

    Un bloque válido arranca con ``---\n``, sigue con claves YAML y
    cierra con ``---\n``. La búsqueda acepta (y consume) los
    newlines/blank line que separan el cierre del cuerpo. Si no hay
    bloque válido, devuelve el input intacto preservando cualquier
    whitespace inicial.
    """
    stripped = markdown.lstrip()
    if not stripped.startswith(_FRONTMATTER_OPENING):
        return markdown
    m = _FRONTMATTER_LEADING_RE.match(stripped)
    if m is None:
        return markdown
    leading_ws = markdown[: len(markdown) - len(stripped)]
    return leading_ws + stripped[m.end():]


def parse_front_matter(markdown: str) -> dict[str, Any] | None:
    """Devuelve el dict YAML del front matter al inicio del markdown, o ``None``.

    Equivalente inverso de :func:`render_front_matter`: extrae el
    bloque ``---\\n...\\n---\\n`` inicial, lo parsea con
    ``yaml.safe_load`` y devuelve el dict. Si no hay FM válido al
    inicio, devuelve ``None`` (preservando ``strip_existing_front_matter``
    como primitiva pura).

    Útil para K2: cuando se re-corre ``--profile study`` sobre un
    archivo existente, queremos leer el FM previo para preservar
    ``started_at`` / ``finished_at`` editados por el usuario.
    """
    stripped = markdown.lstrip()
    if not stripped.startswith(_FRONTMATTER_OPENING):
        return None
    m = _FRONTMATTER_LEADING_RE.match(stripped)
    if m is None:
        return None
    # El match captura ``---\\n<yaml>\\n---\\n\\n`` y termina en el
    # índice posterior al último newline. Extraemos el contenido
    # YAML: arranca después de ``---\\n`` (offset 4) y termina justo
    # antes del ``---`` de cierre. El cierre arranca en
    # ``m.end() - len('---') - 2`` (el -2 cubre el ``\\n`` final
    # extra que captura el regex ``\\n+``).
    fm_text = stripped[
        len(_FRONTMATTER_OPENING) + 1 : m.end() - len(_FRONTMATTER_OPENING) - 2
    ]
    try:
        parsed = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def render_front_matter(fields: dict[str, Any]) -> str:
    """Serializa ``fields`` como un bloque front matter entre ``---``.

    Devuelve un string que arranca con ``---\\n``, contiene el YAML en
    block style y cierra con ``---\\n\\n`` (línea en blanco final para
    separar visualmente del markdown que viene después).
    """
    dumped = yaml.safe_dump(
        fields,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{dumped}---\n\n"


def build_front_matter_fields(
    *,
    title: str,
    book_slug: str,
    chapter_slug: str,
    pages: list[int] | None,
    source_file: str | None,
    source_sha256: str | None,
    converted_at: str,
    capmd_version: str,
    cleaners_applied: tuple[str, ...],
    markitdown_version: str | None = None,
    study_tags: tuple[str, ...] | None = None,
    study_reading_status: str | None = None,
    study_started_at: str | None = None,
    study_finished_at: str | None = None,
) -> dict[str, Any]:
    """Arma el dict de las 10 claves del roadmap en el orden del schema.

    Si los kwargs ``study_*`` se pasan y alguno diverge del neutro,
    agrega una sub-key ``study:`` con los 4 campos (K2). Si todos son
    neutrales (o no se pasan), NO agrega la sub-key (compat con FMs
    pre-K2).
    """
    md_version = markitdown_version if markitdown_version is not None else _md_version()
    fields: dict[str, Any] = {
        "title": title,
        "book": book_slug,
        "chapter": chapter_slug,
        "pages": pages,
        "source_file": source_file,
        "source_sha256": source_sha256,
        "converted_at": converted_at,
        "capmd_version": capmd_version,
        "markitdown_version": md_version,
        "cleaners_applied": list(cleaners_applied),
    }

    # K2: sub-bloque study opcional. Solo se emite si hay data study
    # (alguno de los 4 kwargs fue pasado y diverge del neutro).
    study_block = _maybe_study_block(
        tags=study_tags,
        reading_status=study_reading_status,
        started_at=study_started_at,
        finished_at=study_finished_at,
    )
    if study_block is not None:
        fields["study"] = study_block

    return fields


def _maybe_study_block(
    *,
    tags: tuple[str, ...] | None,
    reading_status: str | None,
    started_at: str | None,
    finished_at: str | None,
) -> dict[str, Any] | None:
    """Devuelve el sub-dict ``study`` si hay data no-neutra; ``None`` si no.

    Detección: si los 4 kwargs vienen en su valor neutro
    (``tags=()``, ``reading_status="unread"``, ``started_at=None``,
    ``finished_at=None``) o no se pasan (``None``), no emite el bloque.
    """
    if tags is None and reading_status is None and started_at is None and finished_at is None:
        return None
    resolved_tags = tags if tags is not None else _NEUTRAL_TAGS
    resolved_status = reading_status if reading_status is not None else _NEUTRAL_STATUS
    resolved_started = started_at
    resolved_finished = finished_at
    if (
        tuple(resolved_tags) == _NEUTRAL_TAGS
        and resolved_status == _NEUTRAL_STATUS
        and resolved_started is None
        and resolved_finished is None
    ):
        return None
    return {
        "tags": list(resolved_tags),
        "reading_status": resolved_status,
        "started_at": resolved_started,
        "finished_at": resolved_finished,
    }


def _md_version() -> str:
    """Wrapper para evitar shadowing con el kwarg ``markitdown_version``."""
    return markitdown_version()


def front_matter_fields_from_capmd_json(json_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Regenera los 10 campos del front matter a partir de un ``capmd.json`` (F3).

    Mapea las keys del JSON a las del FM (mismos nombres que
    :func:`build_front_matter_fields`, así el resultado es directo-
    pasable a :func:`render_front_matter`)::

        JSON                FM
        -----------------   -----------------
        title               title
        book_slug           book
        chapter_slug        chapter
        pages               pages
        source_file         source_file
        source_sha256       source_sha256
        generated_at        converted_at
        capmd_version       capmd_version
        markitdown_version  markitdown_version
        cleaners_applied    cleaners_applied

    Si el JSON trae los campos opcionales de ``study`` (K2), también
    los propaga como sub-dict ``study:``. Valida que
    ``schema_version == 2``. ``KeyError`` si falta alguna key requerida.
    """
    if json_dict.get("schema_version") != 2:
        raise ValueError(
            f"capmd.json schema_version debe ser 2, "
            f"recibido {json_dict.get('schema_version')!r}"
        )
    missing = [k for k in _FM_REQUIRED_KEYS if k not in json_dict]
    if missing:
        raise KeyError(
            f"capmd.json no tiene las keys necesarias para regenerar el FM: "
            f"{missing}"
        )
    fields: dict[str, Any] = {
        "title": json_dict["title"],
        "book": json_dict["book_slug"],
        "chapter": json_dict["chapter_slug"],
        "pages": list(json_dict["pages"]) if json_dict["pages"] is not None else None,
        "source_file": json_dict["source_file"],
        "source_sha256": json_dict["source_sha256"],
        "converted_at": json_dict["generated_at"],
        "capmd_version": json_dict["capmd_version"],
        "markitdown_version": json_dict["markitdown_version"],
        "cleaners_applied": tuple(json_dict["cleaners_applied"]),
    }

    # K2: si el JSON trae los 4 campos opcionales de study y ALGUNO
    # diverge del neutro, agregamos el sub-bloque ``study:``. Misma
    # regla que ``build_front_matter_fields``. ``.get(k)`` devuelve
    # ``None`` tanto si la key está ausente como si está presente con
    # valor ``None``; ``tuple(... or ())`` normaliza lista-a-tupla y
    # tolera ausentes/None.
    study_block = _maybe_study_block(
        tags=tuple(json_dict.get("study_tags") or ()),
        reading_status=json_dict.get("reading_status"),
        started_at=json_dict.get("started_at"),
        finished_at=json_dict.get("finished_at"),
    )
    if study_block is not None:
        fields["study"] = study_block

    return fields


def prepend_front_matter(markdown: str, fields: dict[str, Any]) -> str:
    """Quita front matter previo (idempotencia) y prepende el nuevo bloque."""
    body = strip_existing_front_matter(markdown)
    return render_front_matter(fields) + body
