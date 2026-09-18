"""Renderers de output para el comparador de motores (K5).

Dos formatos soportados:

- ``table``: tabla Rich con colores por estado (green/yellow/red).
  Default.
- ``json``: JSON pretty-print. Útil para tooling externo (pipe a
  ``jq``, integración con scripts).
"""

from __future__ import annotations

import io
import json
from typing import Literal

from rich.box import ROUNDED
from rich.console import Console
from rich.table import Table

from capmd.compare.motors import CompareReport

__all__ = ["render_json", "render_report", "render_table"]


RenderFormat = Literal["table", "json"]


_STATUS_STYLES = {
    "ok": "[green]ok[/green]",
    "skipped": "[yellow]skipped[/yellow]",
    "error": "[red]error[/red]",
}


def render_table(report: CompareReport) -> str:
    """Renderiza el :class:`CompareReport` como tabla Rich a un string."""
    table = Table(
        title=(
            f"[bold]Comparador de motores[/bold] — {report.source.name}"
            + (f" (páginas {report.pages})" if report.pages else "")
            + f"  ·  [dim]total: {report.elapsed_seconds:.2f}s[/dim]"
        ),
        box=ROUNDED,
        show_lines=True,
    )
    table.add_column("Motor", style="bold")
    table.add_column("Palabras", justify="right")
    table.add_column("Headings", justify="right")
    table.add_column("Tiempo (s)", justify="right")
    table.add_column("Estado", justify="center")
    table.add_column("Detalle / error", style="dim", overflow="fold")

    for motor in report.motors:
        status = _STATUS_STYLES.get(motor.status, motor.status)
        detail = motor.error or ""
        if motor.status == "ok":
            words = str(motor.words)
            headings = str(motor.headings)
            time_s = f"{motor.time_seconds:.3f}s"
        else:
            words = "—"
            headings = "—"
            time_s = "—"

        table.add_row(
            motor.name,
            words,
            headings,
            time_s,
            status,
            detail,
        )

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    console.print(table)
    return buf.getvalue().rstrip("\n")


def render_json(report: CompareReport) -> str:
    """Renderiza el :class:`CompareReport` como JSON pretty-print a un string."""
    payload = {
        "source": str(report.source),
        "pages": report.pages,
        "elapsed_seconds": round(report.elapsed_seconds, 4),
        "motors": [
            {
                "name": m.name,
                "words": m.words,
                "headings": m.headings,
                "time_seconds": round(m.time_seconds, 4),
                "status": m.status,
                "error": m.error,
            }
            for m in report.motors
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_report(report: CompareReport, *, format: str = "table") -> str:
    """Dispatch del renderer por ``format`` (``"table"`` o ``"json"``).

    Raises:
        ValueError: si ``format`` no es un valor soportado.
    """
    if format == "table":
        return render_table(report)
    if format == "json":
        return render_json(report)
    raise ValueError(
        f"format inválido: {format!r}; valores soportados: 'table', 'json'"
    )
