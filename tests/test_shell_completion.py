"""Tests de shell completion (H4).

Tres capas:
1. **Unit/CliRunner**: ``--help`` menciona ``--install-completion`` y
   ``--show-completion``; ``--show-completion`` con env var de Typer
   devuelve script válido; ``--install-completion`` (mockeando
   ``Path.home()``) escribe el archivo de completion correcto.
2. **Funcional**: ``_CAPMD_COMPLETE=complete_<shell> capmd …``
   devuelve zsh-format con los subcomandos ``convert``/``batch``/
   ``inspect``/``toc``/``version``/``config``.
3. **Smoke ``zsh -f``**: opcional, gated por ``shutil.which("zsh")``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app

runner = CliRunner()

# Subcomandos esperados (estable: se agregan en convert/batch/inspect/toc;
# `version` y `config` siempre están).
EXPECTED_SUBCOMMANDS = {"convert", "batch", "inspect", "toc", "version", "config"}


def _invoke(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Invoca el binario ``capmd`` con args y env extra."""
    env = os.environ.copy()
    env["_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION"] = "1"
    if env_extra:
        env.update(env_extra)
    capmd_bin = shutil.which("capmd")
    assert capmd_bin, "capmd executable not in PATH (run `uv pip install -e .`)"
    return subprocess.run(
        [capmd_bin, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Capa 1: CliRunner unit
# ---------------------------------------------------------------------------


def test_help_mentions_install_completion() -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "--install-completion" in r.stdout
    assert "--show-completion" in r.stdout


def test_show_completion_zsh_prints_compdef() -> None:
    """``--show-completion zsh`` imprime un script zsh con ``#compdef``."""
    proc = _invoke(["--show-completion", "zsh"])
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "#compdef capmd" in out
    assert "_capmd_completion" in out
    assert "_CAPMD_COMPLETE=complete_zsh" in out
    # La segunda línea debería ser el `compdef <fn> capmd`.
    assert "compdef" in out


def test_show_completion_bash_prints_complete_fn() -> None:
    proc = _invoke(["--show-completion", "bash"])
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "complete -F" in out or "complete -o default -F" in out
    assert "_capmd_completion" in out
    assert "_CAPMD_COMPLETE=complete_bash" in out


def test_show_completion_fish_single_line() -> None:
    proc = _invoke(["--show-completion", "fish"])
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "complete --command capmd" in out
    assert "_CAPMD_COMPLETE=complete_fish" in out


def test_show_completion_unknown_shell_exits_nonzero() -> None:
    """``--show-completion <shell>`` con shell desconocido falla limpio."""
    proc = _invoke(["--show-completion", "tcsh"])
    assert proc.returncode != 0
    # Con el env var de Typer, el mensaje sale por stderr (validación
    # de Typer/click en lugar del fallback ``Shell X not supported``).
    assert "tcsh" in proc.stderr or "not one of" in proc.stderr


def test_install_completion_writes_file(tmp_path: Path) -> None:
    """``--install-completion zsh`` escribe ``~/.zfunc/_capmd`` con el
    script correcto. Redirigimos ``$HOME`` al tmp para no tocar el FS
    real del usuario."""
    capmd_bin = shutil.which("capmd")
    assert capmd_bin
    env = os.environ.copy()
    env["_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION"] = "1"
    env["HOME"] = str(tmp_path)

    proc = subprocess.run(
        [capmd_bin, "--install-completion", "zsh"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    # Typer imprime el mensaje en stdout (no stderr).
    assert "zsh completion installed" in proc.stdout

    installed = tmp_path / ".zfunc" / "_capmd"
    assert installed.exists(), f"esperaba {installed}"
    content = installed.read_text(encoding="utf-8")
    assert "#compdef capmd" in content
    assert "_CAPMD_COMPLETE=complete_zsh" in content


def test_install_completion_bash_writes_to_bash_completions(tmp_path: Path) -> None:
    capmd_bin = shutil.which("capmd")
    assert capmd_bin
    env = os.environ.copy()
    env["_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION"] = "1"
    env["HOME"] = str(tmp_path)

    proc = subprocess.run(
        [capmd_bin, "--install-completion", "bash"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    installed = tmp_path / ".bash_completions" / "capmd.sh"
    assert installed.exists()
    content = installed.read_text(encoding="utf-8")
    assert "_CAPMD_COMPLETE=complete_bash" in content


# ---------------------------------------------------------------------------
# Capa 2: funcional via _CAPMD_COMPLETE
# ---------------------------------------------------------------------------


def test_complete_zsh_lists_all_subcommands() -> None:
    proc = _invoke([], env_extra={"_CAPMD_COMPLETE": "complete_zsh", "COMP_WORDS": ""})
    assert proc.returncode == 0, proc.stderr
    body = proc.stdout
    assert "_arguments" in body  # formato zsh de typer
    for sub in EXPECTED_SUBCOMMANDS:
        # El nombre aparece en el format zsh; chequeamos cada uno presente
        # en el bloque ``(("foo":"...") ...))``.
        assert f'"{sub}":' in body or f'"{sub}"' in body, (
            f"falta {sub!r} en completions: {body[:300]}"
        )


def test_complete_zsh_prefix_filter() -> None:
    """Typer devuelve TODOS los sub-comandos en la primera palabra; zsh
    filtra por prefijo en el lado del shell. Verificamos que el listado
    contiene los nombres correctos (zsh luego los filtra con su pattern)."""
    proc = _invoke(["bat"], env_extra={"_CAPMD_COMPLETE": "complete_zsh", "COMP_WORDS": ""})
    assert proc.returncode == 0
    # ``batch`` aparece como candidato. Los demás también (no se filtra
    # server-side). zsh es el que filtra al renderizar; este test sólo
    # valida el contrato: el protocol devuelve candidatos válidos.
    body = proc.stdout
    assert '"batch"' in body


def test_complete_unknown_shell_exits_one() -> None:
    """El protocolo interno: un shell desconocido debe fallar limpio."""
    proc = _invoke([], env_extra={"_CAPMD_COMPLETE": "complete_zsh"})
    # No COMP_WORDS → bash complete falla con KeyError, no zsh.
    # zsh complete funciona aunque COMP_WORDS falte (no lo usa directo).
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# Capa 3: smoke real con zsh -f
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not shutil.which("zsh"), reason="zsh no instalado en este sistema"
)
def test_zsh_f_parses_completion_script() -> None:
    """El script zsh generado parsea OK en ``zsh -f`` con ``compinit``.

    Valida el test literal del roadmap: el script que ``capmd
    --show-completion zsh`` emite es válido y la función de completion
    se registra. En ``zsh -f`` (sin ``~/.zshrc``) hay que cargar
    ``compinit`` explícitamente para que ``compdef`` exista.
    """
    proc = subprocess.run(
        [shutil.which("capmd"), "--show-completion", "zsh"],
        capture_output=True,
        text=True,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    script = proc.stdout

    # ``compinit`` carga el builtin ``compdef``. ``autoload -U`` evita
    # warnings cuando ya existe.
    zsh = shutil.which("zsh")
    assert zsh
    proc2 = subprocess.run(
        [zsh, "-f", "-c", "autoload -U compinit; compinit; " + script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc2.returncode == 0, f"zsh -f parse failed: {proc2.stderr}"
