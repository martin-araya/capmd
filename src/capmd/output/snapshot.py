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

from capmd.errors import IOError

__all__ = ["write_raw_snapshot"]


def write_raw_snapshot(
    raw_markdown: str,
    *,
    output_path: Path | None,
) -> Path:
    """Escribe ``raw_markdown`` en ``<dest>/.capmd/raw.md`` y devuelve la ruta.

    Parameters
    ----------
    raw_markdown:
        Contenido del markdown pre-limpieza. Hoy es el output de
        ``Engine.convert_*``; mañana será ese output antes de pasar
        por la pipeline de cleaners.
    output_path:
        Ruta del output final del CLI (``-o``). Si es ``None``
        (output a stdout) se usa ``Path.cwd()``.

    Returns
    -------
    Path:
        Ruta absoluta del archivo ``raw.md`` escrito.

    Raises
    ------
    IOError:
        Si no se puede crear ``.capmd/`` o escribir el archivo
        (``exit_code=7``). El mensaje original del ``OSError`` se
        incluye como ``hint``.
    """
    dest = output_path.parent.resolve() if output_path is not None else Path.cwd().resolve()
    snapshot_dir = dest / ".capmd"
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover
        raise IOError(  # pragma: no cover
            f"no se pudo crear el directorio de snapshot: {snapshot_dir}",
            hint=str(exc),
        ) from exc

    raw_path = snapshot_dir / "raw.md"
    try:
        raw_path.write_text(raw_markdown, encoding="utf-8")
    except OSError as exc:
        raise IOError(
            f"no se pudo escribir el snapshot: {raw_path}",
            hint=str(exc),
        ) from exc

    return raw_path
