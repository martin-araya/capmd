"""Renderizado de salida para el CLI.

Funciones puras que convierten modelos de capmd en artefactos de
presentación (hoy: ``rich.tree.Tree`` y dict JSON). Viven en su propio
módulo para que ``cli.py`` se quede solo con parsing y orquestación, y
para que sean testeables sin pasar por ``CliRunner``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.tree import Tree

from capmd.models import Chapter

__all__ = ["chapters_to_json_dict", "render_outline_tree"]


def chapters_to_json_dict(
    source: Path,
    chapters: list[Chapter],
    *,
    total_pages: int,
) -> dict[str, Any]:
    """Serializa el outline a un dict listo para ``json.dumps``.

    Esquema (versión 1, congelado en C10):

        ``{"source": str, "total_pages": int, "chapters": [...]}``

    Cada capítulo expone:

      - ``index`` (1-based, igual que ``Chapter.index``)
      - ``title``
      - ``level``
      - ``start_page``
      - ``end_page_inclusive`` (display; == ``Chapter.end_page - 1``)

    El caller decide cómo serializar (``json.dumps(payload,
    ensure_ascii=False, indent=2)`` suele ser el default correcto).
    """
    return {
        "source": source.name,
        "total_pages": total_pages,
        "chapters": [
            {
                "index": c.index,
                "title": c.title,
                "level": c.level,
                "start_page": c.start_page,
                "end_page_inclusive": c.end_page_inclusive,
            }
            for c in chapters
        ],
    }


def render_outline_tree(source: Path, chapters: list[Chapter]) -> Tree:
    """Devuelve un :class:`rich.tree.Tree` con el outline del PDF.

    La raíz lleva el nombre del archivo. Cada entrada se muestra como
    ``<título>  (p. <start_page>)`` o ``(p. <start>-<end_inclusive>)``
    cuando :func:`capmd.sources.pdf.infer_ranges` ya pobló ``end_page``.
    La indentación la maneja ``rich.tree`` a partir de la jerarquía
    parent/child que reconstruimos desde el campo ``level`` de cada
    :class:`Chapter`.

    La lista de entrada se espera en orden DFS (lo que devuelve
    :func:`capmd.sources.pdf.read_outline`); si no lo está, el árbol
    resultante puede anidar de forma surprising — la fase que llama es
    responsable del orden.
    """
    root = Tree(f"[bold]{source.name}[/bold]")
    if not chapters:
        return root

    # Stack de (nodo_del_árbol, nivel). El nivel del root es 0 para que
    # cualquier chapter.level >= 1 sea hijo directo suyo en la primera
    # iteración.
    stack: list[tuple[Tree, int]] = [(root, 0)]

    for chapter in chapters:
        # Subir hasta encontrar un padre con nivel estrictamente menor.
        while stack and stack[-1][1] >= chapter.level:
            stack.pop()
        parent = stack[-1][0] if stack else root
        if chapter.end_page > chapter.start_page:
            page_label = f"p. {chapter.start_page}-{chapter.end_page_inclusive}"
        else:
            page_label = f"p. {chapter.start_page}"  # pragma: no cover
        branch = parent.add(f"{chapter.title}  [dim]({page_label})[/dim]")
        stack.append((branch, chapter.level))

    return root
