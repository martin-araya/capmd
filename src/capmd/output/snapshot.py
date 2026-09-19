"""Snapshot del markdown crudo (B6).

Cuando la pipeline de cleaners exista (D1+), ``write_raw_snapshot``
seguirá siendo el lugar donde se persiste el markdown *antes* de la
limpieza. El diff entre ``.capmd/raw.md`` y el output final que sale
por ``-o``/stdout muestra exactamente qué hizo cada cleaner.

Por ahora (sin cleaners) el snapshot y el output final son byte-
iguales; eso es lo que el test literal de B6 verifica.
"""

from __future__ import annotations

from pathlib import Path

from capmd.errors import IOError as CapmdIOError

__all__ = ["write_raw_snapshot"]


def write_raw_snapshot(
    raw_markdown: str,
    *,
    output_path: Path | None = None,
    out_dir: Path | None = None,
    book_slug: str | None = None,
    chapter_slug: str | None = None,
) -> Path:
    """Escribe ``raw_markdown`` y devuelve la ruta absoluta del archivo.

    Resolución del destino (FIX-4 / D4):

    - ``output_path`` no-None (single-file mode ``-o``):
      ``<output.parent>/.capmd/raw.md``.
    - ``out_dir`` + ``book_slug`` + ``chapter_slug`` (tree mode ``--out``):
      ``<out_dir>/<book_slug>/<chapter_slug>/.capmd/raw.md``.
    - Si ninguno está provisto (stdout mode): fallback a
      ``Path.cwd()/.capmd/raw.md`` (compatibilidad con tests legacy).

    Parameters
    ----------
    raw_markdown:
        Contenido del markdown pre-limpieza.
    output_path:
        Ruta del output single-file (``-o``). Mutuamente excluyente
        con ``out_dir``.
    out_dir, book_slug, chapter_slug:
        Tree mode: destino del snapshot dentro del chapter dir.

    Returns
    -------
    Path:
        Ruta absoluta del archivo ``raw.md`` escrito.

    Raises
    ------
    CapmdIOError:
        ``exit_code = 7``. El mensaje original del ``OSError`` se
        incluye como ``hint``.
    """
    if output_path is not None:
        dest = output_path.parent
    elif (
        out_dir is not None
        and book_slug is not None
        and chapter_slug is not None
    ):
        dest = out_dir / book_slug / chapter_slug
    else:
        dest = Path.cwd().resolve()

    snapshot_dir = dest / ".capmd"
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover
        raise CapmdIOError(  # pragma: no cover
            f"no se pudo crear el directorio de snapshot: {snapshot_dir}",
            hint=str(exc),
        ) from exc

    raw_path = snapshot_dir / "raw.md"
    try:
        raw_path.write_text(raw_markdown, encoding="utf-8")
    except PermissionError as exc:
        # FIX-6: permission denied en el snapshot también → rc=5 con
        # hint específico del path que falló.
        from capmd.errors import PermissionDenied as _PD
        from capmd.output._atomic import _format_permission_hint
        raise _PD(
            f"sin permisos para escribir el snapshot: {raw_path}",
            hint=_format_permission_hint(exc),
        ) from exc
    except OSError as exc:
        raise CapmdIOError(
            f"no se pudo escribir el snapshot: {raw_path}",
            hint=str(exc),
        ) from exc

    return raw_path
