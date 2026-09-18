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
