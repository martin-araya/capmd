"""``capmd open`` — abrir el .md resultante en el editor (H5).

Single source of truth para "abrir un archivo en el editor del usuario":

- Precedencia: ``--editor`` arg → ``$EDITOR`` env var → ``open`` (macOS).
- Fire-and-forget: no esperamos al editor.
- Subprocess mockeable via el param ``spawn`` (testing).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

__all__ = ["open_in_editor", "resolve_editor_command"]


class _Spawn(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        stdin: Any = ...,
        stdout: Any = ...,
        stderr: Any = ...,
        **kw: Any,
    ) -> subprocess.Popen[Any]: ...


def resolve_editor_command(
    editor: str | None,
    *,
    platform: str | None = None,
    env_editor: str | None = None,
) -> list[str]:
    """Resuelve el argv base para invocar el editor.

    Args:
        editor: override explícito (CLI ``--editor`` o param de la API).
        platform: override de ``sys.platform`` (testing). ``None`` = real.
        env_editor: override de ``$EDITOR`` (testing). ``None`` = real env.

    Returns:
        argv base (sin el path a abrir), por ejemplo:

        - ``["code", "--wait"]`` si ``editor="code --wait"``.
        - ``["vim"]`` si ``$EDITOR="vim"``.
        - ``["open"]`` en macOS si no hay editor.

    Raises:
        typer.BadParameter: si no hay editor posible (no $EDITOR y
            no-macOS). El caller lo mapea a exit 2.
    """
    import typer

    resolved_platform = platform if platform is not None else sys.platform
    resolved_editor = env_editor if env_editor is not None else os.environ.get("EDITOR")

    chosen = editor or resolved_editor
    if chosen:
        try:
            return shlex.split(chosen)
        except ValueError as exc:
            raise typer.BadParameter(
                f"--editor inválido (no se pudo parsear como shell words): {exc}"
            ) from None

    if resolved_platform == "darwin":
        return ["open"]

    raise typer.BadParameter(
        "no se puede determinar el editor: pasá --editor <cmd> o exportá $EDITOR "
        "(en macOS también funciona sin nada: usa `open`)"
    )


def open_in_editor(
    path: Path,
    *,
    editor: str | None = None,
    spawn: _Spawn | None = None,
    platform: str | None = None,
    env_editor: str | None = None,
) -> None:
    """Abre ``path`` en el editor. Fire-and-forget.

    Args:
        path: ruta absoluta o relativa al archivo a abrir.
        editor: override del comando editor (string; se ``shlex.split``).
        spawn: factory de Popen para testing. ``None`` = ``subprocess.Popen``.
        platform: override de ``sys.platform`` (testing).
        env_editor: override de ``$EDITOR`` (testing).

    Raises:
        typer.BadParameter: si no hay editor posible.
        FileNotFoundError: si el binario del editor no existe (lo deja
            propagar para que el caller decida; en CLI lo mapeamos a
            exit 2).

    Notas:
        - No llama ``.wait()``.
        - Usa ``stdin=DEVNULL`` para evitar que el editor lea la stdin
          de capmd.
        - ``stdout`` y ``stderr`` se heredan del proceso para que el
          usuario vea errores del editor si los hay.
    """
    if not path.exists():
        from capmd.errors import SourceNotFound

        raise SourceNotFound(
            f"no se encontró el archivo a abrir: {path}",
            hint="verificá la ruta",
        )

    argv_base = resolve_editor_command(
        editor,
        platform=platform,
        env_editor=env_editor,
    )
    argv = [*argv_base, str(path)]

    popen = spawn if spawn is not None else subprocess.Popen
    popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
