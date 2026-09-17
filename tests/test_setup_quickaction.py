"""Tests del Quick Action / Atajos de macOS (I2).

Cubre:
- Estructura del ``.shortcut`` plist que se distribuye con el paquete.
- API :mod:`capmd.setup_quickaction`: ``plan_install``, ``plan_uninstall``,
  ``install``, ``uninstall``, ``resolve_shortcut_path``.
- Subcomando CLI ``capmd setup quick-action`` (``--help``, ``--dry-run``,
  ``--print-cmd``, instalacion off-macOS rechazada, etc.).

Los tests que asumen macOS van con ``pytest.mark.skipif(sys.platform != "darwin")``.
Los que parsean el plist son independientes de la plataforma.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from capmd.assets import SHORTCUT_NAME
from capmd.errors import CapmdError
from capmd.setup_quickaction import (
    PlanResult,
    install,
    load_shortcut_metadata,
    plan_install,
    plan_uninstall,
    resolve_shortcut_path,
    shell_script_body,
    shortcut_action_identifiers,
    uninstall,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shipped_shortcut_path() -> Path:
    """Devuelve la ruta al .shortcut shippeado, copiándolo a un path estable."""
    return resolve_shortcut_path()


# ---------------------------------------------------------------------------
# Estructura del .shortcut (independiente de la plataforma)
# ---------------------------------------------------------------------------

def test_shipped_shortcut_is_a_binary_plist() -> None:
    p = _shipped_shortcut_path()
    data = load_shortcut_metadata(p)
    assert isinstance(data, dict)
    assert "WFWorkflowActions" in data
    assert "WFWorkflowClientVersion" in data


def test_shipped_shortcut_named_convert_capmd_chapter() -> None:
    p = _shipped_shortcut_path()
    data = load_shortcut_metadata(p)
    assert data.get("WFWorkflowName") == SHORTCUT_NAME
    assert SHORTCUT_NAME in p.name


def test_shipped_shortcut_contains_run_shell_script_action() -> None:
    p = _shipped_shortcut_path()
    ids = shortcut_action_identifiers(p)
    assert "is.workflow.actions.runshellscript" in ids, (
        f"el shortcut no tiene Run Shell Script; ids={ids}"
    )


def test_shipped_shortcut_runs_capmd_convert() -> None:
    p = _shipped_shortcut_path()
    body = shell_script_body(p)
    assert "capmd" in body, "el shell script no menciona capmd"
    assert "--pages" in body or "range" in body, (
        "el shell script no parece soportar --pages o un prompt de rango"
    )


def test_shipped_shortcut_handles_capmd_not_found() -> None:
    p = _shipped_shortcut_path()
    body = shell_script_body(p)
    assert "capmd no encontrado" in body or "no encontrado" in body, (
        "el shell script no maneja el caso de capmd ausente"
    )
    assert "uv tool install" in body, (
        "el shell script no apunta al comando de instalación correcto"
    )


def test_shipped_shortcut_sets_output_dir_to_downloads_capmd() -> None:
    p = _shipped_shortcut_path()
    body = shell_script_body(p)
    assert "Downloads/capmd" in body or "Downloads" in body, (
        "el shell script no define ~/Downloads/capmd como carpeta de salida por default"
    )


def test_shipped_shortcut_discoverable_for_finder() -> None:
    """El atributo WFWorkflowIsDiscoverable=True lo hace aparecer en Quick Actions."""
    p = _shipped_shortcut_path()
    data = load_shortcut_metadata(p)
    assert data.get("WFWorkflowIsDiscoverable") is True


# ---------------------------------------------------------------------------
# API: plan_install / plan_uninstall
# ---------------------------------------------------------------------------

def test_plan_install_uses_open_command() -> None:
    plan = plan_install(shortcut_path=Path("/tmp/fake.shortcut"))
    cmds = plan.commands
    assert len(cmds) == 1
    label, argv = cmds[0]
    assert label == "open"
    assert argv[0] == "open"
    assert argv[1] == "/tmp/fake.shortcut"


def test_plan_install_is_dry_run_safe() -> None:
    """`plan_install` no toca el filesystem."""
    assert isinstance(plan_install(shortcut_path=Path("/tmp/dry.shortcut")), PlanResult)


def test_plan_uninstall_uses_applescript() -> None:
    plan = plan_uninstall()
    cmds = plan.commands
    assert len(cmds) == 1
    label, argv = cmds[0]
    assert label == "applescript"
    assert argv[0] == "osascript"
    joined = " ".join(argv)
    assert SHORTCUT_NAME in joined, (
        f"el AppleScript no menciona el nombre del shortcut; joined={joined!r}"
    )
    assert "delete shortcut" in joined


# ---------------------------------------------------------------------------
# API: install / uninstall (off-macOS)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "darwin", reason="testea el path off-macOS")
def test_install_refuses_on_non_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    with pytest.raises(CapmdError) as exc_info:
        install(shortcut_path=Path("/tmp/dummy.shortcut"))
    err = exc_info.value
    assert "macOS" in str(err) or "darwin" in str(err)
    assert err.code == 2


@pytest.mark.skipif(sys.platform == "darwin", reason="testea el path off-macOS")
def test_uninstall_refuses_on_non_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    with pytest.raises(CapmdError) as exc_info:
        uninstall()
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# API: resolve_shortcut_path
# ---------------------------------------------------------------------------

def test_resolve_shortcut_path_with_override_returns_verbatim(tmp_path: Path) -> None:
    f = tmp_path / "x.shortcut"
    f.write_bytes(b"x")
    assert resolve_shortcut_path(override=f) == f


def test_resolve_shortcut_path_default_materialises_resource() -> None:
    p = resolve_shortcut_path()
    assert p.exists()
    assert p.suffix == ".shortcut"
    # Debe ser un plist parseable.
    data = load_shortcut_metadata(p)
    assert "WFWorkflowActions" in data


# ---------------------------------------------------------------------------
# CLI: capmd setup quick-action
# ---------------------------------------------------------------------------

def _cli_runner() -> Path:
    """Resuelve el binario `capmd` para usar con subprocess."""
    from shutil import which

    found = which("capmd")
    if not found:
        pytest.skip("capmd binary not in PATH; run `uv pip install -e .`")
    return Path(found)


def test_setup_quickaction_help_lists_install_dry_run_print_cmd() -> None:
    bin_path = _cli_runner()
    proc = subprocess.run(
        [str(bin_path), "setup", "quick-action", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "--install" in out, f"--install no aparece en --help:\n{out}"
    assert "--uninstall" in out, f"--uninstall no aparece en --help:\n{out}"
    assert "--dry-run" in out, f"--dry-run no aparece en --help:\n{out}"
    assert "--print-cmd" in out, f"--print-cmd no aparece en --help:\n{out}"


def test_setup_quickaction_dry_run_does_not_modify_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--dry-run` debe imprimir el plan y NO invocar `open`."""
    bin_path = _cli_runner()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("untouched")
    fake_shortcut = tmp_path / "x.shortcut"
    fake_shortcut.write_bytes(b"x")

    proc = subprocess.run(
        [
            str(bin_path),
            "setup",
            "quick-action",
            "--dry-run",
            "--path",
            str(fake_shortcut),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "open" in out, f"--dry-run no muestra `open`:\n{out}"
    assert str(fake_shortcut) in out
    assert sentinel.read_text() == "untouched"


def test_setup_quickaction_print_cmd_exits_0(
    tmp_path: Path,
) -> None:
    bin_path = _cli_runner()
    fake_shortcut = tmp_path / "y.shortcut"
    fake_shortcut.write_bytes(b"x")
    proc = subprocess.run(
        [
            str(bin_path),
            "setup",
            "quick-action",
            "--print-cmd",
            "--path",
            str(fake_shortcut),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    assert "open" in proc.stdout
    assert str(fake_shortcut) in proc.stdout


@pytest.mark.skipif(sys.platform == "darwin", reason="testea el path off-macOS")
def test_setup_quickaction_refuses_on_linux() -> None:
    bin_path = _cli_runner()
    proc = subprocess.run(
        [str(bin_path), "setup", "quick-action", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 2, (
        f"debería fallar con rc=2 fuera de macOS, got {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = proc.stdout + proc.stderr
    assert "macOS" in combined or "darwin" in combined
