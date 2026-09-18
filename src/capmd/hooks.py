"""Hook runner para el post-conversión de ``capmd`` (K3).

Lee ``[hooks].post_command`` del TOML (con override por
``[books.<id>].post_command``) y ejecuta el comando después de que el
``.md` final fue escrito a disco. El hook recibe:

- La ruta al archivo como ``$1`` (arg posicional).
- Metadata vía env vars:
  - ``CAPMD_OUTPUT_PATH``
  - ``CAPMD_CAPMD_JSON_PATH`` (tree mode; ``None`` en flat/stdout)
  - ``CAPMD_IMAGES_DIR`` (tree mode; ``None`` cuando no hay imágenes)
  - ``CAPMD_BOOK_SLUG`` / ``CAPMD_CHAPTER_SLUG``
  - ``CAPMD_PROFILE`` (perfil activo: ``"study"``, etc.)
  - ``CAPMD_VERSION``

El hook **NO** se invoca cuando la conversión no escribe a disco
(stdout), bajo ``--dry-run``, o cuando la conversión falló antes del
write. Si el comando devuelve exit code != 0, expira por timeout, o
no existe, ``run_post_command`` captura el resultado y devuelve un
:class:`HookResult` con los tails; **no levanta excepción**.

El caller (CLI) decide cómo reportar el warning a stderr; el runner
solo expone los datos.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import capmd

__all__ = [
    "HOOK_OUTPUT_TAIL_LINES",
    "HOOK_TIMEOUT_DEFAULT",
    "HOOK_VAR_BOOK_SLUG",
    "HOOK_VAR_CAPMD_JSON_PATH",
    "HOOK_VAR_CHAPTER_SLUG",
    "HOOK_VAR_IMAGES_DIR",
    "HOOK_VAR_OUTPUT_PATH",
    "HOOK_VAR_PROFILE",
    "HOOK_VAR_VERSION",
    "HookContext",
    "HookResult",
    "build_hook_env",
    "run_post_command",
]


HOOK_TIMEOUT_DEFAULT: float = 60.0
"""Timeout default para ``run_post_command`` (segundos)."""

HOOK_OUTPUT_TAIL_LINES: int = 20
"""Cantidad máxima de líneas a retener de stdout/stderr del hook."""

HOOK_VAR_OUTPUT_PATH: str = "CAPMD_OUTPUT_PATH"
HOOK_VAR_CAPMD_JSON_PATH: str = "CAPMD_CAPMD_JSON_PATH"
HOOK_VAR_IMAGES_DIR: str = "CAPMD_IMAGES_DIR"
HOOK_VAR_BOOK_SLUG: str = "CAPMD_BOOK_SLUG"
HOOK_VAR_CHAPTER_SLUG: str = "CAPMD_CHAPTER_SLUG"
HOOK_VAR_PROFILE: str = "CAPMD_PROFILE"
HOOK_VAR_VERSION: str = "CAPMD_VERSION"


@dataclass(frozen=True)
class HookContext:
    """Metadata que se le pasa al hook como env vars + $1."""

    output_path: Path
    capmd_json_path: Path | None
    images_dir: Path | None
    book_slug: str
    chapter_slug: str
    profile: str


@dataclass(frozen=True)
class HookResult:
    """Resultado de ejecutar el hook (o de saltearlo)."""

    command: str
    returncode: int
    stdout_tail: str
    stderr_tail: str
    duration_seconds: float
    timed_out: bool
    skipped: bool

    @property
    def succeeded(self) -> bool:
        """``True`` si el hook corrió y devolvió exit code 0."""
        return (not self.skipped) and (not self.timed_out) and self.returncode == 0


def build_hook_env(ctx: HookContext) -> dict[str, str]:
    """Construye el dict de env vars a pasar al subprocess.

    Hereda ``os.environ`` (incluye ``PATH``, ``HOME``, etc.) y pisa/agre-
    ga las 7 vars ``CAPMD_*`` con strings (no Path, porque subprocess
    requiere str o bytes).
    """
    env: dict[str, str] = dict(os.environ)
    env[HOOK_VAR_OUTPUT_PATH] = str(ctx.output_path)
    env[HOOK_VAR_CAPMD_JSON_PATH] = (
        str(ctx.capmd_json_path) if ctx.capmd_json_path is not None else ""
    )
    env[HOOK_VAR_IMAGES_DIR] = (
        str(ctx.images_dir) if ctx.images_dir is not None else ""
    )
    env[HOOK_VAR_BOOK_SLUG] = ctx.book_slug
    env[HOOK_VAR_CHAPTER_SLUG] = ctx.chapter_slug
    env[HOOK_VAR_PROFILE] = ctx.profile
    env[HOOK_VAR_VERSION] = capmd.__version__
    return env


def _truncate(text: str, max_lines: int = HOOK_OUTPUT_TAIL_LINES) -> str:
    """Devuelve las últimas ``max_lines`` líneas del texto.

    Si el texto tiene menos líneas que ``max_lines``, lo devuelve intacto.
    """
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[-max_lines:])


def run_post_command(
    command: str | None,
    ctx: HookContext,
    *,
    timeout: float = HOOK_TIMEOUT_DEFAULT,
) -> HookResult:
    """Ejecuta ``command`` con el ctx como env vars + $1=ctx.output_path.

    Comportamiento:
      - Si ``command`` es ``None`` o vacío (después de ``strip()``) →
        devuelve :class:`HookResult` con ``skipped=True``.
      - Si ``shlex.split(command)`` falla → ``HookResult(returncode=-1,
        stderr_tail=...)``, sin raise.
      - Si el binario no existe (``FileNotFoundError``) o no se puede
        ejecutar (``OSError``) → ``HookResult(returncode=-1,
        stderr_tail=...)``, sin raise.
      - Si supera ``timeout`` (``TimeoutExpired``) → ``HookResult(
        timed_out=True, returncode=-1, stderr_tail=...)``, sin raise.
      - Si devuelve exit code != 0 → ``HookResult(returncode=<n>)``, sin raise.
      - Si todo sale bien → ``HookResult(returncode=0)``.

    Args:
        command: comando a ejecutar (``shlex.split``-able). ``$1`` se
            appendea al final del argv con la ruta absoluta al ``.md``.
        ctx: metadata a pasar como env vars.
        timeout: segundos antes de matar el subprocess (``-1`` =
            sin timeout).
    """
    if not command or not command.strip():
        return HookResult(
            command=command or "",
            returncode=0,
            stdout_tail="",
            stderr_tail="",
            duration_seconds=0.0,
            timed_out=False,
            skipped=True,
        )

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return HookResult(
            command=command,
            returncode=-1,
            stdout_tail="",
            stderr_tail=f"invalid command syntax: {exc}",
            duration_seconds=0.0,
            timed_out=False,
            skipped=False,
        )

    env = build_hook_env(ctx)
    full_argv = [*argv, str(ctx.output_path)]

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            full_argv,
            shell=False,
            env=env,
            timeout=None if timeout < 0 else timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return HookResult(
            command=command,
            returncode=-1,
            stdout_tail="",
            stderr_tail=f"command not found: {exc}",
            duration_seconds=time.perf_counter() - start,
            timed_out=False,
            skipped=False,
        )
    except OSError as exc:
        return HookResult(
            command=command,
            returncode=-1,
            stdout_tail="",
            stderr_tail=f"OS error running hook: {exc}",
            duration_seconds=time.perf_counter() - start,
            timed_out=False,
            skipped=False,
        )
    except subprocess.TimeoutExpired as exc:
        return HookResult(
            command=command,
            returncode=-1,
            stdout_tail=_truncate(
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            ),
            stderr_tail=_truncate(
                (
                    exc.stderr.decode("utf-8", errors="replace")
                    if isinstance(exc.stderr, bytes)
                    else (exc.stderr or "")
                )
                + f"\ntimeout after {timeout}s",
            ),
            duration_seconds=time.perf_counter() - start,
            timed_out=True,
            skipped=False,
        )

    return HookResult(
        command=command,
        returncode=proc.returncode,
        stdout_tail=_truncate(proc.stdout or ""),
        stderr_tail=_truncate(proc.stderr or ""),
        duration_seconds=time.perf_counter() - start,
        timed_out=False,
        skipped=False,
    )


def hook_failed_message(result: HookResult) -> str | None:
    """Devuelve un mensaje corto para reportar fallos, o ``None`` si OK."""
    if result.skipped:
        return None
    if result.timed_out:
        return (
            f"hook timed out after {result.duration_seconds:.1f}s "
            f"(command: {result.command!r})"
        )
    if result.returncode != 0:
        return (
            f"hook exited with code {result.returncode} "
            f"(command: {result.command!r}, took {result.duration_seconds:.1f}s)"
        )
    return None


def _ensure_ctx_for_tests(ctx: Any) -> HookContext:  # pragma: no cover
    """Helper para tests: coerción silenciosa de dicts a :class:`HookContext`."""
    if isinstance(ctx, HookContext):
        return ctx
    return HookContext(**ctx)
