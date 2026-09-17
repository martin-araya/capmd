"""Protocolo :class:`Source` para los lectores por formato.

Las implementaciones concretas viven en :mod:`capmd.sources.pdf`,
:mod:`capmd.sources.epub` y :mod:`capmd.sources.office`. La fase C1
solo necesita el método ``read_outline``; el resto se agrega en fases
posteriores a medida que se necesitan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from capmd.models import Chapter


class Source(Protocol):
    """Contrato mínimo que cumple cada lector de formato."""

    def read_outline(self, path: Path) -> list[Chapter]:  # pragma: no cover - Protocol
        """Devuelve el outline aplanado en orden de aparición.

        Entradas cuya página no se puede resolver se descartan (con un
        warning). PDFs sin outline devuelven ``[]``.
        """
        ...
