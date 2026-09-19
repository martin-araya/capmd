"""Atomic write helper compartido.

BUGS.md MEDIUM #8: evita que el reader vea un archivo truncado si el
proceso muere entre ``open()`` y ``close()`` (Ctrl-C, OOM, SIGTERM).
El rename atómico del kernel completa la operación en un solo paso.

Reusado por cache, output writer, output snapshot y CLI single-file
write. Existe como módulo separado para que ``capmd.cache`` no sea
una dependencia de ``capmd.output`` (inversión indeseable).
"""

from __future__ import annotations

from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Escribe ``content`` a ``path`` atómicamente (tmp + rename)."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _format_permission_hint(exc: OSError) -> str:
    """FIX-6: construye un hint accionable para ``PermissionError``.

    Inspecciona ``OSError.filename`` (archivo que falló) y
    ``OSError.filename2`` (segundo archivo, típico de link/rename).
    Apunta al directorio padre, que es donde el usuario suele tener
    que ajustar permisos.

    Si ``exc.filename`` es None (caso raro), devuelve un hint
    genérico que sigue siendo útil.
    """
    failed = getattr(exc, "filename", None) or getattr(exc, "filename2", None)
    if failed is not None:
        failed_path = Path(failed)
        # Apuntamos siempre al directorio padre: el archivo fallido
        # muchas veces aún no existe (es el path destino del write),
        # así que no podemos usar ``is_dir()``.
        return (
            f"verificá que '{failed_path.parent}' sea escribible por tu usuario"
        )
    return "verificá los permisos del directorio de salida"
