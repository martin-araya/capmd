"""Progress bars para ``capmd convert`` (H1).

Wrapper sobre :mod:`rich.progress` que expone 5 stages secuenciales
(recorte → conversión → limpieza → imágenes → escritura) y respeta
los flags ``--quiet`` y la detección de TTY.

Cuando ``quiet=True`` o stderr no es TTY, ``stages()`` rinde un handle
no-op: ningún método toca I/O real. Esto garantiza que
``capmd --quiet convert ...`` produzca ``stderr == ""``.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

__all__ = ["StageHandle", "silent_console_text_io", "stages"]


class _NoopBackend:
    """Backend que ignora todas las operaciones."""

    def start(self, label: str, *, total: int | None) -> int:
        return 0

    def advance(self, task_id: int, *, steps: int) -> None:
        return None

    def stop(self, task_id: int) -> None:
        return None


class _RichBackend:
    """Backend que envuelve un ``rich.progress.Progress`` activo."""

    def __init__(self, progress: Any) -> None:
        self._progress = progress

    def start(self, label: str, *, total: int | None) -> int:
        result = self._progress.add_task(label, total=total)
        return int(result)  # type: ignore[no-any-return, unused-ignore]

    def advance(self, task_id: int, *, steps: int) -> None:
        self._progress.advance(task_id, steps)

    def stop(self, task_id: int) -> None:
        with suppress(Exception):
            self._progress.update(task_id, visible=False)


class StageHandle:
    """Handle público de stages. Delega a un backend concreto."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def start(self, label: str, *, total: int | None = None) -> int:
        return int(self._backend.start(label, total=total))

    def advance(self, task_id: int, *, steps: int = 1) -> None:
        self._backend.advance(task_id, steps=steps)

    def stop(self, task_id: int) -> None:
        self._backend.stop(task_id)


def _stderr_is_tty() -> bool:
    try:
        return bool(sys.stderr.isatty())
    except (AttributeError, ValueError):
        return False


@contextmanager
def stages(
    *,
    quiet: bool,
    force_terminal: bool | None = None,
    is_tty: bool | None = None,
) -> Iterator[StageHandle]:
    """Context manager de las 5 stages del convert.

    Args:
        quiet: si True, todo es no-op (stderr queda vacío).
        force_terminal: override del autodetect de rich. Útil en tests
            para forzar render incluso cuando stderr no es TTY real.
        is_tty: override de ``sys.stderr.isatty()``. ``None`` = usar
            el valor real.

    Yields:
        :class:`StageHandle`. Los métodos ``start/advance/stop`` siempre
        están disponibles; en modo quiet son pass-through.
    """
    tty = _stderr_is_tty() if is_tty is None else bool(is_tty)

    if quiet or not tty:
        yield StageHandle(_NoopBackend())
        return

    try:
        from rich.console import Console
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TaskProgressColumn,
            TextColumn,
            TimeElapsedColumn,
        )
    except ImportError:  # pragma: no cover - rich es dep declarada
        yield StageHandle(_NoopBackend())
        return

    console = Console(
        stderr=True,
        force_terminal=bool(force_terminal) if force_terminal is not None else None,
        file=sys.stderr,
    )
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
    )
    progress.start()
    try:
        yield StageHandle(_RichBackend(progress))
    finally:
        progress.stop()


def silent_console_text_io() -> io.StringIO:
    """Devuelve un ``io.StringIO`` para redirigir ``Console(stderr=True)``.

    Usado por ``cli`` para silenciar los ``_stderr.print(...)``
    decorativos cuando ``--quiet`` está activo.
    """
    return io.StringIO()
