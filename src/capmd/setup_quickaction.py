"""Installer for the macOS Quick Action that wires Finder into ``capmd``.

Workflow
--------

``capmd setup quick-action --install`` materialises the bundled ``.shortcut``
to a writable temp path and invokes ``open`` on it.  macOS Shortcuts.app
catches the open event and shows its standard "Add Shortcut" sheet; the user
clicks *Add* and the shortcut lands in their ``~/Library/Shortcuts/`` (and in
the *Quick Actions* submenu of Finder's right-click menu because the plist
sets ``WFWorkflowIsDiscoverable = True``).

``capmd setup quick-action --uninstall`` deletes the shortcut from the user's
Shortcuts library via AppleScript (the ``shortcuts`` CLI does not expose a
``delete`` subcommand; it only knows ``run``/``list``/``view``/``sign``).

Why plistlib and not Shortcuts.app automation
--------------------------------------------

``shortcuts`` (the macOS CLI bundled with Shortcuts.app) has no ``create``,
``import`` or ``export`` subcommand.  Shortcuts.app's AppleScript dictionary
exposes ``make new shortcut`` but does not let us attach actions to the new
shortcut — the action graph of a shortcut can only be modified in the GUI.
So the ``.shortcut`` that ships with capmd is **hand-rolled** at build time
by ``scripts/build-quick-action.py``.  See that script for the rationale and
the iteration tips.
"""

from __future__ import annotations

import contextlib
import plistlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from importlib.resources import as_file
from pathlib import Path
from typing import Any, cast

from capmd.assets import SHORTCUT_NAME, SHORTCUT_RESOURCE
from capmd.errors import CapmdError

__all__ = [
    "SHORTCUT_NAME",
    "PlanResult",
    "install",
    "plan_install",
    "plan_uninstall",
    "resolve_shortcut_path",
    "uninstall",
]


@dataclass(frozen=True)
class PlanResult:
    """A planned set of side-effects (filesystem + subprocess invocations).

    ``capmd setup quick-action --dry-run`` returns this so the user can see
    exactly what would change without anything happening.  Tests inspect the
    same object to verify behaviour without touching the user's machine.
    """

    files_to_create: list[Path] = field(default_factory=list)
    files_to_remove: list[Path] = field(default_factory=list)
    commands: list[tuple[str, list[str]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        """Human-readable description of the plan, one line per item."""
        out: list[str] = []  # pragma: no cover
        for p in self.files_to_create:  # pragma: no cover
            out.append(f"create file: {p}")  # pragma: no cover
        for p in self.files_to_remove:  # pragma: no cover
            out.append(f"remove file: {p}")  # pragma: no cover
        for label, argv in self.commands:  # pragma: no cover
            cmd = " ".join(_quote(arg) for arg in argv)  # pragma: no cover
            out.append(f"{label}: {cmd}")  # pragma: no cover
        for n in self.notes:  # pragma: no cover
            out.append(f"note: {n}")  # pragma: no cover
        return out  # pragma: no cover


def _quote(s: str) -> str:
    return f"'{s}'" if any(ch.isspace() for ch in s) else s  # pragma: no cover


class QuickActionNotSupportedError(CapmdError):
    """Raised when ``capmd setup quick-action`` runs off macOS."""

    code = 2


def _ensure_macos() -> None:
    if sys.platform != "darwin":
        raise QuickActionNotSupportedError(
            "el Quick Action de Finder solo existe en macOS; estás en "
            f"{sys.platform}.  El atajo no aplica."
        )


def resolve_shortcut_path(override: Path | None = None) -> Path:
    """Return a concrete filesystem path to the shipped ``.shortcut``.

    With no ``override`` this copies the package resource to a stable temp
    path (the resource lives inside the wheel which is itself inside a zip —
    external tools like ``open`` need a real filesystem path).  The temp file
    is removed at interpreter exit via ``atexit``.

    When ``override`` is given (typically by tests) the override is returned
    verbatim and the caller owns its lifecycle.
    """
    import atexit

    if override is not None:
        return override

    target_dir = Path(tempfile.mkdtemp(prefix="capmd-quickaction-"))
    target = target_dir / f"{SHORTCUT_NAME}.shortcut"
    with as_file(SHORTCUT_RESOURCE) as src:
        shutil.copy2(src, target)
    atexit.register(_rmtree_best_effort, target_dir)
    return target


def _rmtree_best_effort(path: Path) -> None:
    with contextlib.suppress(OSError):  # pragma: no cover
        shutil.rmtree(path, ignore_errors=True)  # pragma: no cover


def plan_install(shortcut_path: Path | None = None) -> PlanResult:
    """Plan the steps needed to install the Quick Action.

    Does no I/O.  See :func:`install` for the executing variant.
    """
    _ensure_macos()
    src = resolve_shortcut_path(shortcut_path)

    plan = PlanResult(
        files_to_create=[],
        files_to_remove=[],
        commands=[("open", ["open", str(src)])],
        notes=[
            "Shortcuts.app mostrará la hoja \"Add Shortcut\".  Hacé click en "
            "Add (o Configure si querés revisar el graph antes) para finalizar.",
        ],
    )
    return plan


def plan_uninstall(shortcut_path: Path | None = None) -> PlanResult:
    """Plan the steps to remove the Quick Action from the user's library."""
    _ensure_macos()
    plan = PlanResult(
        commands=[
            (
                "applescript",
                [
                    "osascript",
                    "-e",
                    f'tell application "Shortcuts" to delete shortcut "{SHORTCUT_NAME}"',
                ],
            ),
        ],
        notes=[
            "Si el shortcut no existe, el comando emite un error de AppleScript que "
            "se ignora silenciosamente — la operación se considera idempotente.",
        ],
    )
    return plan


def install(shortcut_path: Path | None = None) -> None:
    """Execute the install plan: ``open`` the .shortcut for Shortcuts.app."""
    plan = plan_install(shortcut_path)
    _run_open(plan.commands[0][1])


def uninstall() -> None:
    """Execute the uninstall plan: delete the shortcut via AppleScript."""
    plan = plan_uninstall()
    _, argv = plan.commands[0]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode not in (0, 1):
        # AppleScript returns nonzero for "not found"; treat as success.
        # Other nonzero rc is a real failure.
        raise QuickActionNotSupportedError(
            f"failed to delete shortcut via AppleScript (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


def _run_open(argv: list[str]) -> None:
    """Run ``open`` against the .shortcut, surfacing errors as CapmdError."""
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:  # pragma: no cover
        raise QuickActionNotSupportedError(
            f"`{' '.join(argv)}` exited {proc.returncode}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


# ---------------------------------------------------------------------------
# Plist introspection helpers used by tests and by ``capmd setup --print-cmd``.
# These do not call any macOS APIs; they just parse the shipped `.shortcut`
# file so we can assert its structure without launching Shortcuts.app.
# ---------------------------------------------------------------------------


def load_shortcut_metadata(path: Path) -> dict[str, Any]:
    """Parse the binary plist and return the top-level dict."""
    with path.open("rb") as fh:
        return cast("dict[str, Any]", plistlib.load(fh))


def shortcut_action_identifiers(path: Path) -> list[str]:
    """Return the list of ``WFWorkflowActionIdentifier`` values in the shortcut."""
    data = load_shortcut_metadata(path)
    return [
        str(a["WFWorkflowActionIdentifier"]) for a in data.get("WFWorkflowActions", [])
    ]


def shell_script_body(path: Path) -> str:
    """Return the embedded shell script body of the first Run Shell Script action."""
    data = load_shortcut_metadata(path)
    for a in data.get("WFWorkflowActions", []):  # pragma: no cover
        if a.get("WFWorkflowActionIdentifier") == "is.workflow.actions.runshellscript":  # pragma: no cover
            params = a.get("WFWorkflowActionParameters", {})
            script_value = params.get("Script", {}).get("Value")
            if isinstance(script_value, str):  # pragma: no cover
                return script_value
    return ""  # pragma: no cover
