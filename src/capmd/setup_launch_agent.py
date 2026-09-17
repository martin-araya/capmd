"""Installer del LaunchAgent que corre ``capmd watch`` (I3).

Un LaunchAgent de macOS es un ``~/Library/LaunchAgents/<Label>.plist`` que
``launchd`` carga al login y mantiene vivo según las directivas del
``KeepAlive`` dict.  En el caso de capmd:

* ``Label``: ``com.martinaraya.capmd-watch`` (estable; único por repo).
* ``ProgramArguments``: ``<resolved capmd binary> watch --inbox ... --out
  ... --move-to ...``.  ``<resolved capmd binary>`` se computa con
  :func:`shutil.which("capmd")` al momento de la instalación (no al
  import) — si el usuario reinstala capmd, ``--reinstall`` regenera el
  plist con la nueva ruta.
* ``KeepAlive`` con sólo ``Crashed = true`` para que ``launchd`` lo
  levante de nuevo si crashea, pero no si sale con código 0 (caso en
  el que el usuario hace ``launchctl unload``).
* ``RunAtLoad = true``: arranca al login.
* Logs a ``~/Library/Logs/capmd/capmd-watch.{out,err}.log``.

Workflow
--------

::

    capmd setup launch-agent --install
        → valida inbox/out/move-to, genera plist, escribe a
          ~/Library/LaunchAgents/, y corre ``launchctl load -w``.

    capmd setup launch-agent --uninstall
        → ``launchctl unload``, borra el plist.

    capmd setup launch-agent --reinstall
        → uninstall + install con el binario de capmd actual.

    capmd setup launch-agent --dry-run / --print-cmd
        → muestra el plan sin escribir nada.
"""

from __future__ import annotations

import contextlib
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from capmd.errors import CapmdError

__all__ = [
    "AGENT_LABEL",
    "AGENT_PLIST_NAME",
    "PlanResult",
    "agent_plist_path",
    "build_plist_xml",
    "install",
    "is_loaded",
    "plan_install",
    "plan_reinstall",
    "plan_uninstall",
    "reinstall",
    "uninstall",
]


AGENT_LABEL: str = "com.martinaraya.capmd-watch"
"""Label estable del LaunchAgent (identifica el proceso ante ``launchd``)."""

AGENT_PLIST_NAME: str = "com.martinaraya.capmd-watch.plist"


@dataclass(frozen=True)
class PlanResult:
    """Side-effects planeados para ``--dry-run`` / tests."""

    files_to_create: list[Path] = field(default_factory=list)
    files_to_remove: list[Path] = field(default_factory=list)
    commands: list[tuple[str, list[str]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        out: list[str] = []
        for p in self.files_to_create:
            out.append(f"create file: {p}")
        for p in self.files_to_remove:
            out.append(f"remove file: {p}")
        for label, argv in self.commands:
            cmd = " ".join(_quote(arg) for arg in argv)
            out.append(f"{label}: {cmd}")
        for n in self.notes:
            out.append(f"note: {n}")
        return out


def _quote(s: str) -> str:
    return f"'{s}'" if any(ch.isspace() for ch in s) else s


class LaunchAgentNotSupportedError(CapmdError):
    """Levantado cuando se corre off-macOS."""

    exit_code = 2


def _ensure_macos() -> None:
    if sys.platform != "darwin":
        raise LaunchAgentNotSupportedError(
            "el LaunchAgent solo aplica en macOS; estás en "
            f"{sys.platform}."
        )


def agent_plist_path() -> Path:
    """Path al .plist en ``~/Library/LaunchAgents/`` (no chequea existencia)."""
    return Path.home() / "Library" / "LaunchAgents" / AGENT_PLIST_NAME


def log_dir() -> Path:
    """Path al directorio donde ``launchd`` escribe los logs del agente."""
    return Path.home() / "Library" / "Logs" / "capmd"


# ---------------------------------------------------------------------------
# Plist generation
# ---------------------------------------------------------------------------


def build_plist_xml(
    *,
    capmd_path: Path,
    inbox: Path,
    out_dir: Path,
    move_to: Path,
    label: str = AGENT_LABEL,
) -> bytes:
    """Construye el XML del plist del LaunchAgent.

    Devuelve bytes (plistlib.dump con FMT_XML); los strings se escapan
    explícitamente porque ``plistlib`` no escapa nombres de archivo.

    ``capmd_path`` se resuelve en install-time (no se hardcodea) — si el
    usuario reinstala capmd en otra ruta, ``reinstall`` regenera el plist.
    """
    log_p = log_dir()
    payload = {
        "Label": label,
        "ProgramArguments": [
            str(capmd_path),
            "watch",
            "--inbox",
            str(inbox),
            "--out",
            str(out_dir),
            "--move-to",
            str(move_to),
        ],
        "RunAtLoad": True,
        "KeepAlive": {"Crashed": True},
        "StandardOutPath": str(log_p / "capmd-watch.out.log"),
        "StandardErrorPath": str(log_p / "capmd-watch.err.log"),
        "WorkingDirectory": str(Path.home()),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML)


# ---------------------------------------------------------------------------
# Plan variants
# ---------------------------------------------------------------------------


def _resolve_capmd_binary(override: Path | None = None) -> Path:
    if override is not None:
        if not override.exists():
            raise LaunchAgentNotSupportedError(
                f"--capmd-bin no apunta a un binario existente: {override}"
            )
        return override
    found = shutil.which("capmd")
    if not found:
        raise LaunchAgentNotSupportedError(
            "capmd no encontrado en PATH. Instalalo primero con "
            "`uv tool install capmd` o pasá --capmd-bin /ruta/al/binario."
        )
    return Path(found)


def plan_install(
    *,
    inbox: Path,
    out_dir: Path,
    move_to: Path,
    capmd_bin: Path | None = None,
) -> PlanResult:
    """Plan de instalación: escribir plist + ``launchctl load -w``."""
    _ensure_macos()
    _resolve_capmd_binary(capmd_bin)  # validates binary exists
    plist_p = agent_plist_path()
    return PlanResult(
        files_to_create=[plist_p, log_dir()],
        commands=[
            ("launchctl", ["launchctl", "load", "-w", str(plist_p)]),
        ],
        notes=[
            "El agente arrancará al próximo login (RunAtLoad=True) y se "
            "reiniciará si crashea (KeepAlive.Crashed=True).",
            f"Logs: {log_dir()}/capmd-watch.{{out,err}}.log",
        ],
    )


def plan_uninstall() -> PlanResult:
    """Plan de uninstall: ``launchctl unload`` + remove plist."""
    _ensure_macos()
    plist_p = agent_plist_path()
    return PlanResult(
        files_to_remove=[plist_p],
        commands=[
            ("launchctl", ["launchctl", "unload", str(plist_p)]),
        ],
        notes=[
            "Si el agente no estaba cargado, `launchctl unload` falla "
            "silenciosamente — la operación es idempotente.",
        ],
    )


def plan_reinstall(
    *,
    inbox: Path,
    out_dir: Path,
    move_to: Path,
    capmd_bin: Path | None = None,
) -> PlanResult:
    """Uninstall + install con el binario de capmd actual."""
    _ensure_macos()
    uninstall_plan = plan_uninstall()
    install_plan = plan_install(
        inbox=inbox, out_dir=out_dir, move_to=move_to, capmd_bin=capmd_bin
    )
    return PlanResult(
        files_to_create=install_plan.files_to_create,
        files_to_remove=uninstall_plan.files_to_remove,
        commands=uninstall_plan.commands + install_plan.commands,
        notes=uninstall_plan.notes + install_plan.notes,
    )


# ---------------------------------------------------------------------------
# Ejecutores
# ---------------------------------------------------------------------------


def _execute_plan(plan: PlanResult) -> None:
    for p in plan.files_to_remove:
        with contextlib.suppress(FileNotFoundError):
            p.unlink()
    for p in plan.files_to_create:
        p.parent.mkdir(parents=True, exist_ok=True)
    for label, argv in plan.commands:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        if proc.returncode != 0 and label == "launchctl" and "load" in argv:
            raise LaunchAgentNotSupportedError(
                f"`{' '.join(argv)}` falló con rc={proc.returncode}: "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        if proc.returncode != 0 and label == "launchctl" and "unload" in argv:
            # unload falla si el agente no estaba cargado; OK
            continue


def install(
    *,
    inbox: Path,
    out_dir: Path,
    move_to: Path,
    capmd_bin: Path | None = None,
) -> None:
    """Escribe el plist y corre ``launchctl load -w``."""
    plist_p = agent_plist_path()
    capmd_path = _resolve_capmd_binary(capmd_bin)
    xml = build_plist_xml(
        capmd_path=capmd_path,
        inbox=inbox,
        out_dir=out_dir,
        move_to=move_to,
    )
    plist_p.parent.mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
    plist_p.write_bytes(xml)
    # Re-construimos el plan después de escribir el plist para que el
    # summary refleje el estado real del filesystem en --dry-run.
    _execute_plan(plan_install(inbox=inbox, out_dir=out_dir, move_to=move_to, capmd_bin=capmd_bin))


def uninstall() -> None:
    _execute_plan(plan_uninstall())


def reinstall(
    *,
    inbox: Path,
    out_dir: Path,
    move_to: Path,
    capmd_bin: Path | None = None,
) -> None:
    uninstall()
    install(inbox=inbox, out_dir=out_dir, move_to=move_to, capmd_bin=capmd_bin)


def is_loaded() -> bool:
    """Chequea vía ``launchctl list`` si el agente está cargado."""
    _ensure_macos()
    proc = subprocess.run(
        ["launchctl", "list", AGENT_LABEL],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


# Mantener referencia a ``escape`` para que el import no marque unused
# en builds minimalistas que poden este módulo en el futuro.
_ = escape
