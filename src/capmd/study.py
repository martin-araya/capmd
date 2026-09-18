"""Perfiles de output para el CLI de ``capmd`` (K2).

El primer perfil es ``study``: agrega un sub-bloque ``study:`` al front
matter (F2) con ``tags``, ``reading_status``, ``started_at`` y
``finished_at``, y appendea tres secciones vacías (``## Resumen`` /
``## Conceptos clave`` / ``## Dudas``) al final del cuerpo del markdown
para que el usuario tenga un template listo para llenar.

Precedencia de campos:

- ``tags`` → CLI ``--tag`` (repetible) > book profile TOML > ``[]``.
- ``reading_status`` → CLI ``--reading-status`` > book profile TOML > ``"unread"``.
- ``started_at`` / ``finished_at`` → se setean automáticamente cuando
  ``--reading-status in_progress`` o ``read`` se pasa por CLI y el
  valor existente es ``None``. Sin ``--reset-study``, los timestamps
  editados manualmente por el usuario se preservan en re-corridas.

Diseño extensible: ``PROFILES`` es la tupla de perfiles soportados; cada
perfil implementa su propia lógica de mutación de markdown + FM. Por
ahora solo ``"study"``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "DEFAULT_READING_STATUS",
    "DEFAULT_TAGS",
    "PROFILES",
    "READING_STATUSES",
    "apply_profile_study",
    "merge_study_fields",
    "neutral_study_values",
    "study_sections_block",
    "validate_reading_status",
]


PROFILES: tuple[str, ...] = ("study",)
"""Tupla de perfiles soportados. El dispatcher en ``cli.py`` despacha
por nombre a la función ``apply_profile_<name>``."""

READING_STATUSES: tuple[str, ...] = ("unread", "in_progress", "read")
"""Enum cerrado de valores válidos para ``reading_status``."""

DEFAULT_READING_STATUS: str = "unread"
"""Default cuando no se pasa CLI ni book profile."""

DEFAULT_TAGS: tuple[str, ...] = ()
"""Default cuando no se pasa CLI ni book profile."""


def validate_reading_status(value: str) -> str:
    """Valida ``value`` contra :data:`READING_STATUSES`. Devuelve el valor.

    Raises:
        ValueError: si ``value`` no está en :data:`READING_STATUSES`.
    """
    if value not in READING_STATUSES:
        raise ValueError(
            f"reading_status inválido: {value!r}. "
            f"Valores válidos: {', '.join(READING_STATUSES)}"
        )
    return value


def study_sections_block() -> str:
    """Devuelve el bloque de 3 secciones vacías separadas por blank lines.

    Formato literal (matches README:573-580)::

        ## Resumen

        ## Conceptos clave

        ## Dudas

    El bloque NO termina en newline (lo agrega el caller si quiere un
    separador extra contra el cuerpo previo).
    """
    return "## Resumen\n\n## Conceptos clave\n\n## Dudas"


def neutral_study_values() -> dict[str, Any]:
    """Devuelve los valores neutrales del perfil study (sin actividad).

    Usado por ``output/writer.py`` y ``output/frontmatter.py`` para
    decidir si emitir el sub-bloque ``study:`` en el YAML/JSON o
    omitirlo entero (mantiene retrocompatibilidad con ``capmd.json``
    y FMs pre-K2).
    """
    return {
        "tags": tuple(DEFAULT_TAGS),
        "reading_status": DEFAULT_READING_STATUS,
        "started_at": None,
        "finished_at": None,
    }


def _is_neutral(fields: Mapping[str, Any]) -> bool:
    """``True`` si ``fields`` no diverge de los valores neutrales."""
    return (
        tuple(fields.get("tags", ())) == tuple(DEFAULT_TAGS)
        and fields.get("reading_status", DEFAULT_READING_STATUS) == DEFAULT_READING_STATUS
        and fields.get("started_at") is None
        and fields.get("finished_at") is None
    )


def _now_iso(now: datetime | None = None) -> str:
    """ISO 8601 UTC con sufijo ``Z``. Inyectable para tests."""
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dedupe_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    """Dedup preservando orden de aparición."""
    return tuple(dict.fromkeys(tags))


def merge_study_fields(
    *,
    cli_tags: tuple[str, ...] = (),
    cli_status: str | None = None,
    cli_reset: bool = False,
    existing_tags: tuple[str, ...] | None = None,
    existing_status: str | None = None,
    existing_started: str | None = None,
    existing_finished: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resuelve los 4 campos del estudio con precedencia y auto-timestamps.

    Precedencia:
      1. CLI (``cli_tags`` / ``cli_status``) gana si viene no-vacío / no-None.
      2. Si no hay CLI, ``existing_tags`` / ``existing_status``.
      3. Defaults: ``[]`` y ``"unread"``.

    Timestamps:
      - ``started_at``: si el CLI pidió ``in_progress`` y ``existing_started``
        es ``None``, se setea a ``now``. Si ya hay valor, se preserva
        (incluso si el CLI vuelve a pedir ``in_progress``) salvo
        ``cli_reset=True``.
      - ``finished_at``: idem con ``read``.

    Args:
        cli_tags: lista cruda de ``--tag X`` (puede tener duplicados;
            se deduplican preservando orden).
        cli_status: valor de ``--reading-status`` (``None`` si no se pasó).
        cli_reset: ``True`` para forzar ``started_at`` y ``finished_at`` a
            ``None`` (override de preservacion).
        existing_tags/started/finished: valores leídos del front matter
            previo del archivo destino.
        existing_status: ``reading_status`` previo (``None`` = sin FM previo).
        now: override del reloj (tests deterministas).

    Returns:
        ``dict`` con keys ``tags``, ``reading_status``, ``started_at``,
        ``finished_at``. ``tags`` ya viene deduplicado.
    """
    # Resolver tags: CLI > existing > default.
    if cli_tags:
        tags = _dedupe_tags(tuple(cli_tags))
    elif existing_tags is not None:
        tags = tuple(existing_tags)
    else:
        tags = tuple(DEFAULT_TAGS)

    # Resolver status: CLI > existing > default. Validar siempre.
    if cli_status is not None:
        status = validate_reading_status(cli_status)
    elif existing_status is not None:
        status = validate_reading_status(existing_status)
    else:
        status = DEFAULT_READING_STATUS

    # Resolver timestamps.
    now_iso = _now_iso(now)

    if cli_reset:
        # Reset explícito: ambos timestamps a None, sin importar CLI status.
        started_at = None
        finished_at = None
    else:
        started_at = existing_started
        finished_at = existing_finished

        # Auto-set si CLI pidió el status correspondiente y el valor es None.
        if cli_status == "in_progress" and started_at is None:
            started_at = now_iso
        if cli_status == "read" and finished_at is None:
            finished_at = now_iso

    return {
        "tags": tags,
        "reading_status": status,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def apply_profile_study(
    *,
    markdown: str,
    cli_tags: tuple[str, ...] = (),
    cli_status: str | None = None,
    cli_reset: bool = False,
    existing_fm: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Aplica el perfil ``study`` sobre un markdown ya limpio.

    Pasos:
      1. Resuelve los 4 campos de estudio con :func:`merge_study_fields`
         (si ``existing_fm`` trae ``study: {...}``, se preservan sus
         timestamps salvo ``cli_reset=True``).
      2. Appendea el bloque de secciones vacías al cuerpo.
      3. Si ``markdown`` arranca con front matter YAML, REESCRIBE el
         bloque FM agregando/actualizando la sub-key ``study:``.
         Si no tiene FM, devuelve el markdown con las secciones appendeadas
         (sin FM).

    Args:
        markdown: el markdown limpio (con o sin FM al inicio).
        cli_tags: tags pasados por CLI (``--tag X --tag Y``).
        cli_status: ``--reading-status``.
        cli_reset: forzar reset de timestamps.
        existing_fm: dict del FM previo (alternativa a parsear de ``markdown``).
            Útil para tests que quieren inyectar el estado previo sin
            parsear el markdown completo.
        now: reloj inyectable para tests.

    Returns:
        Tupla ``(markdown_mutado, fields_resueltos)``. ``fields_resueltos``
        es el dict de :func:`merge_study_fields` (los 4 campos ya con
        precedencia aplicada).
    """
    # Importación perezosa para evitar ciclos: frontmatter importa study
    # indirectamente vía tests, y study importa frontmatter solo cuando
    # necesita reescribir el FM.
    from capmd.output.frontmatter import (
        parse_front_matter,
        prepend_front_matter,
        render_front_matter,
        strip_existing_front_matter,
    )

    # 1) Determinar el estado previo.
    parsed_fm = dict(existing_fm) if existing_fm is not None else parse_front_matter(markdown)
    study_block = parsed_fm.get("study") if parsed_fm else None
    if isinstance(study_block, Mapping):
        existing_tags = tuple(study_block.get("tags") or ())
        existing_status = study_block.get("reading_status")
        existing_started = study_block.get("started_at")
        existing_finished = study_block.get("finished_at")
    else:
        existing_tags = None
        existing_status = None
        existing_started = None
        existing_finished = None

    fields = merge_study_fields(
        cli_tags=cli_tags,
        cli_status=cli_status,
        cli_reset=cli_reset,
        existing_tags=existing_tags,
        existing_status=existing_status,
        existing_started=existing_started,
        existing_finished=existing_finished,
        now=now,
    )

    # 2) Appendear secciones vacías al cuerpo (siempre, haya FM o no).
    body = strip_existing_front_matter(markdown)
    body = body.rstrip("\n") + "\n\n" + study_sections_block() + "\n"

    # 3) Re-renderizar FM si había.
    if parsed_fm is None:
        return body, fields

    # Si los campos resueltos son neutrales, NO emitimos la sub-key
    # (mantiene compat con FMs pre-K2 y con runs sin --profile study
    # accidentalmente aplicados).
    new_fm = dict(parsed_fm)
    if _is_neutral(fields):
        new_fm.pop("study", None)
    else:
        new_fm["study"] = {
            "tags": list(fields["tags"]),
            "reading_status": fields["reading_status"],
            "started_at": fields["started_at"],
            "finished_at": fields["finished_at"],
        }

    # Re-render: usamos render_front_matter directo para tener control
    # sobre el orden del dict (sort_keys=False ya está en el helper).
    new_md = render_front_matter(new_fm) + body

    # ``prepend_front_matter`` también sirve pero renderiza twice; ya
    # tenemos el cuerpo limpio y el FM nuevo, no necesitamos su
    # idempotencia acá.
    _ = prepend_front_matter  # mantener el import usado
    return new_md, fields
