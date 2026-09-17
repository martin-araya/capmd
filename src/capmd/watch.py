"""Watcher de carpeta para ``capmd watch`` (I3).

Observa una carpeta (``inbox``) y, por cada archivo nuevo que matchea
``patterns`` y se mantiene estable (mtime + size sin cambios durante
``debounce_secs``), ejecuta ``capmd convert`` y mueve el original a
``move_to``.

Implementación: **polling** con ``os.scandir``.  Sin dependencias nativas
(``watchdog``/FSEvents se consideraron pero no se justifican contra el
resto del stack: ``agent.md`` veta deps nuevas sin justificación y el
polling de 0.5s ya cumple el test literal del roadmap
"soltar un PDF genera la salida en ≤ el tiempo de una conversión manual").
Si en el futuro hace falta FSEvents, el módulo expone :func:`iter_events`
que se puede reimplementar encima de ``watchdog.observers.Observer``
sin tocar el resto.

Diseño
------

Tres piezas desacopladas:

1. :func:`iter_events` — yields :class:`WatchEvent` para cada archivo
   estable que aparece en el inbox.  No toca el filesystem, no llama a
   ``capmd``.  Lo testea unit tests con un ``stop_event`` y ``runner``
   inyectables.
2. :func:`process_event` — corre ``capmd convert`` vía el callback
   inyectable (``runner``), y si la conversión termina bien mueve el
   original a ``move_to``.  Si la conversión falla, el original queda en
   el inbox para retry manual.
3. :func:`run_watch` — loop top-level que une ``iter_events`` y
   ``process_event`` con manejo de SIGINT/SIGTERM.

El CLI (``capmd watch ...``) solo orquesta; toda la lógica vive acá.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from capmd.errors import CapmdError

__all__ = [
    "DEFAULT_PATTERNS",
    "WatchConfig",
    "WatchEvent",
    "iter_events",
    "process_event",
    "run_watch",
]


DEFAULT_PATTERNS: tuple[str, ...] = ("*.pdf", "*.epub", "*.docx", "*.doc")
"""Default file globs capmd acepta como input directo via markitdown."""


@dataclass(frozen=True)
class WatchConfig:
    """Parámetros de una corrida de ``capmd watch``.

    ``inbox``, ``out_dir`` y ``move_to`` son obligatorios.  ``move_to`` se
    crea automáticamente al primer evento.  ``debounce_secs`` evita disparar
    en archivos que están siendo copiados al inbox (los editores escriben
    en chunks).
    """

    inbox: Path
    out_dir: Path
    move_to: Path
    patterns: tuple[str, ...] = DEFAULT_PATTERNS
    debounce_secs: float = 2.0
    poll_interval_secs: float = 0.5
    dry_run: bool = False

    def __post_init__(self) -> None:
        for name in ("inbox", "out_dir", "move_to"):
            value = getattr(self, name)
            if not isinstance(value, Path):
                value = Path(value)
                object.__setattr__(self, name, value)


@dataclass(frozen=True)
class WatchEvent:
    """Una ocurrencia: un archivo en ``inbox`` cuya copia terminó.

    ``mtime`` y ``size`` se usan internamente para confirmar estabilidad
    (el mismo archivo tiene que tener la misma tupla en dos polls
    consecutivos antes de emitirse).
    """

    path: Path
    mtime: float
    size: int


class WatchError(CapmdError):
    """Errores de setup del watcher (inbox no existe, etc.)."""

    exit_code = 7


# ---------------------------------------------------------------------------
# Core: iter_events
# ---------------------------------------------------------------------------


def _matches_any(path: Path, patterns: tuple[str, ...]) -> bool:
    name = path.name
    return any(fnmatch(name, pat) for pat in patterns)


def _scan_candidates(inbox: Path, patterns: tuple[str, ...]) -> Iterator[Path]:
    try:
        with os.scandir(inbox) as it:
            for entry in it:
                if not entry.is_file(follow_symlinks=False):
                    continue
                p = Path(entry.path)
                if _matches_any(p, patterns):
                    yield p
    except FileNotFoundError as exc:
        raise WatchError(
            f"inbox no existe o no es accesible: {inbox}"
        ) from exc
    except NotADirectoryError as exc:
        raise WatchError(
            f"inbox no es un directorio: {inbox}"
        ) from exc


def iter_events(
    cfg: WatchConfig,
    stop_event: threading.Event | None = None,
    *,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[WatchEvent]:
    """Yields :class:`WatchEvent` para cada archivo estable nuevo en ``cfg.inbox``.

    Algoritmo: poll cada ``cfg.poll_interval_secs`` segundos.  Trackea un
    dict ``seen[path] = (mtime, size)``.  Un archivo se emite cuando (a)
    aparece por primera vez, (b) su ``(mtime, size)`` se mantiene sin
    cambios por **dos** polls consecutivos, y (c) su ``mtime`` no cambia en
    ese intervalo (asume que el editor terminó de escribir).

    ``stop_event`` y los callables ``now``/``sleep`` se inyectan para que
    los tests puedan correr sin esperar segundos reales.
    """
    seen: dict[Path, tuple[float, int]] = {}
    stable_count: dict[Path, int] = {}
    poll_no = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        for candidate in _scan_candidates(cfg.inbox, cfg.patterns):
            try:
                stat = candidate.stat()
            except FileNotFoundError:
                # El archivo desapareció entre el scan y el stat; lo
                # purgamos del tracking.
                seen.pop(candidate, None)
                stable_count.pop(candidate, None)
                continue
            key = (stat.st_mtime, stat.st_size)
            prev_key = seen.get(candidate)
            seen[candidate] = key
            if prev_key != key:
                # Cambió desde el último poll: reset stability counter.
                stable_count[candidate] = 1
                continue
            # Igual al último poll: incrementa contador.
            stable_count[candidate] = stable_count.get(candidate, 1) + 1
            # Consideramos estable después de 2 polls (1 poll de "vista
            # previa" + 1 poll de confirmación).  Con poll_interval_secs=0.5s
            # son ~1s + la latencia de un poll.
            if stable_count[candidate] >= 2 and prev_key is not None:
                # Emitir y purgar del tracking para no re-emitir el mismo
                # archivo en cada iteración.
                del stable_count[candidate]
                yield WatchEvent(candidate, stat.st_mtime, stat.st_size)
        poll_no += 1
        if stop_event is not None:
            if stop_event.wait(cfg.poll_interval_secs):
                return
        else:
            sleep(cfg.poll_interval_secs)


# ---------------------------------------------------------------------------
# Core: process_event
# ---------------------------------------------------------------------------


RunnerFn = Callable[[Path, Path], None]
"""Callback que ejecuta ``capmd convert <file> --out <out_dir>``.

Lanza :class:`subprocess.CalledProcessError` si la conversión falla; ese
error se propaga al caller de :func:`process_event` que decide si dejar el
archivo en el inbox o moverlo igual.
"""


def _default_runner(file: Path, out_dir: Path) -> None:
    """Runner default: delega a ``capmd convert`` (asume binario en PATH).

    Usa ``--quiet`` para que ``capmd`` no imprima el F6 report en stderr
    (que en este contexto nadie lo lee y entorpece el log del watcher).

    Pasa ``stdin=DEVNULL`` porque ``capmd`` puede leer de stdin en algunos
    flujos (ej: `-` como source); si hereda el stdin del watcher, puede
    quedar bloqueado esperando input.
    """
    capmd_bin = shutil.which("capmd")
    if not capmd_bin:
        raise WatchError(
            "capmd no encontrado en PATH; instalá con `uv tool install capmd`"
        )
    subprocess.run(
        [capmd_bin, "--quiet", "convert", str(file), "--out", str(out_dir)],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


def _next_versioned_path(target: Path) -> Path:
    """Sufijo numérico incremental si ``target`` ya existe."""
    stem, suffix = target.stem, target.suffix
    parent = target.parent
    n = 1
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1
        if n > 9999:  # guard
            raise WatchError(
                f"demasiadas colisiones versionando {target.name}"
            )


def process_event(
    event: WatchEvent,
    cfg: WatchConfig,
    *,
    runner: RunnerFn | None = None,
) -> bool:
    """Convierte ``event.path`` y mueve el original a ``cfg.move_to``.

    Returns ``True`` si la conversión + el move fueron exitosos; ``False`` si
    la conversión falló (el original queda en el inbox para reintento
    manual).  En ``dry_run`` no se ejecuta nada y devuelve ``True``.

    El ``runner`` se inyecta para tests; default es ``capmd convert`` vía
    subprocess.
    """
    if cfg.dry_run:
        return True

    runner = runner or _default_runner
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    cfg.move_to.mkdir(parents=True, exist_ok=True)

    try:
        runner(event.path, cfg.out_dir)
    except Exception:
        return False

    target = cfg.move_to / event.path.name
    if target.exists():
        target = _next_versioned_path(target)
    try:
        shutil.move(str(event.path), str(target))
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Top-level run_watch
# ---------------------------------------------------------------------------


def run_watch(
    cfg: WatchConfig,
    *,
    runner: RunnerFn | None = None,
    install_signal_handlers: bool = True,
) -> int:
    """Corre el watcher hasta SIGINT/SIGTERM.  Returns el exit code."""
    if not cfg.inbox.exists():
        raise WatchError(f"inbox no existe: {cfg.inbox}")
    if not cfg.inbox.is_dir():
        raise WatchError(f"inbox no es un directorio: {cfg.inbox}")

    stop_event = threading.Event()

    def _stop(signum: int, frame: object) -> None:
        stop_event.set()

    if install_signal_handlers:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

    log = _stderr_log
    if not cfg.dry_run:
        log(f"capmd watch: escuchando {cfg.inbox} (Ctrl-C para detener)")
    else:
        log(f"capmd watch: DRY-RUN, escuchando {cfg.inbox}")

    for event in iter_events(cfg, stop_event):
        ok = process_event(event, cfg, runner=runner)
        if ok:
            log(f"OK: {event.path.name} → {cfg.move_to}/")
        else:
            log(f"FAIL: {event.path.name} quedó en {cfg.inbox}/")
    return 0


def _stderr_log(msg: str) -> None:
    print(msg, file=sys.stderr)
