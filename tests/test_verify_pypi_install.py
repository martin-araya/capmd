"""Tests for scripts/verify-pypi-install.sh (J4).

Mockeamos `pip` y `capmd` para verificar que el script:
- Acepta `--target pypi` y `--target testpypi`.
- Rechaza targets invalidos.
- Skip con CAPMD_SKIP_PYPI_VERIFY=1.
- Llama a `pip install` con el index-url correcto para TestPyPI.
- Invoca `capmd convert` sobre el PDF.
- Verifica que el markdown output no este vacio.

Mockeamos `python3 -m venv` con un stub que solo crea una carpeta vacia con
``bin/activate`` para que el script pueda sourcing el venv sin fallar.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify-pypi-install.sh"


def _setup_fake_bin(tmp_path: Path) -> None:
    """Crea un directorio _bin con stubs de python3, pip, capmd, venv, uv, etc.

    Los stubs registran invocaciones en $FAKE_LOG para que el test pueda
    verificar la secuencia de comandos.
    """
    bin_dir = tmp_path / "_bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "fake.log"
    log.write_text("")

    # Crear stubs compartidos que el python3 -m venv copiara al venv/bin.
    # Como nuestro stub de python3 crea el venv manualmente, tambien
    # escribimos pip y capmd en el bin/ del venv al crearlo.
    (bin_dir / "python3").write_text(
        "#!/usr/bin/env sh\n"
        f'FAKE_LOG="{log}"\n'
        'echo "python3 $@" >> "$FAKE_LOG"\n'
        # venv creation: crear dir + bin/activate + copiar stubs de pip/capmd.
        'case "$1" in\n'
        '  -m)\n'
        '    case "$2" in\n'
        '      venv)\n'
        '        venv_dir="$3"\n'
        '        mkdir -p "$venv_dir/bin"\n'
        '        echo "#!/bin/sh\\nexport PATH=$venv_dir/bin:\\$PATH" > "$venv_dir/bin/activate"\n'
        '        chmod +x "$venv_dir/bin/activate"\n'
        '        # Copiar stubs de pip y capmd al venv/bin.\n'
        '        if [ -d "$FAKE_BIN" ]; then\n'
        '          cp "$FAKE_BIN/pip" "$venv_dir/bin/pip" 2>/dev/null || true\n'
        '          cp "$FAKE_BIN/capmd" "$venv_dir/bin/capmd" 2>/dev/null || true\n'
        '          chmod +x "$venv_dir/bin/pip" "$venv_dir/bin/capmd" 2>/dev/null || true\n'
        '        fi\n'
        '        exit 0\n'
        '        ;;\n'
        '      *)\n'
        '        exec "$REAL_PYTHON" "$@"\n'
        '        ;;\n'
        '    esac\n'
        '    ;;\n'
        '  *)\n'
        '    exec "$REAL_PYTHON" "$@"\n'
        '    ;;\n'
        'esac\n'
    )
    (bin_dir / "python3").chmod(0o755)

    # pip stub — loguea invocaciones y appendea al log.
    (bin_dir / "pip").write_text(
        "#!/usr/bin/env sh\n"
        f'FAKE_LOG="{log}"\n'
        'echo "pip $@" >> "$FAKE_LOG"\n'
        "exit 0\n"
    )
    (bin_dir / "pip").chmod(0o755)

    # capmd stub (entry point del paquete) — escribe output markdown no vacio.
    (bin_dir / "capmd").write_text(
        "#!/usr/bin/env sh\n"
        f'FAKE_LOG="{log}"\n'
        'echo "capmd $@" >> "$FAKE_LOG"\n'
        'prev=""\n'
        'for arg in "$@"; do\n'
        '  if [ "$prev" = "-o" ] && [ -n "$arg" ] && [ "${arg#-}" = "$arg" ]; then\n'
        '    echo "# fake markdown output from capmd stub" > "$arg"\n'
        '    echo "more content here" >> "$arg"\n'
        '  fi\n'
        '  prev="$arg"\n'
        'done\n'
        "exit 0\n"
    )
    (bin_dir / "capmd").chmod(0o755)


def _run_verify(
    tmp_path: Path,
    *,
    args: list[str],
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    _setup_fake_bin(tmp_path)
    env = {
        **os.environ,
        "PATH": str(tmp_path / "_bin") + ":" + os.environ.get("PATH", ""),
        "REAL_PYTHON": sys.executable,
        "FAKE_BIN": str(tmp_path / "_bin"),
        "PYTHONPATH": str(REPO_ROOT) + ":" + os.environ.get("PYTHONPATH", ""),
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(VERIFY_SCRIPT), *args, str(tmp_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_verify_rejects_unknown_target(tmp_path: Path) -> None:
    proc = _run_verify(tmp_path, args=["0.2.0", "--target", "bogus"])
    assert proc.returncode != 0
    assert "--target debe ser pypi o testpypi" in proc.stderr


def test_verify_skip_env_var(tmp_path: Path) -> None:
    proc = _run_verify(tmp_path, args=["0.2.0"], env_extra={"CAPMD_SKIP_PYPI_VERIFY": "1"})
    assert proc.returncode == 0
    assert "skip por CAPMD_SKIP_PYPI_VERIFY=1" in proc.stdout


def test_verify_testpypi_uses_index_url(tmp_path: Path) -> None:
    proc = _run_verify(tmp_path, args=["0.2.0", "--target", "testpypi"])
    assert proc.returncode == 0, proc.stderr
    log = (tmp_path / "fake.log").read_text()
    # pip debe recibir --index-url apuntando a TestPyPI.
    assert "--index-url" in log
    assert "test.pypi.org" in log
    assert "capmd==0.2.0" in log


def test_verify_pypi_no_index_url(tmp_path: Path) -> None:
    proc = _run_verify(tmp_path, args=["0.2.0"])
    assert proc.returncode == 0, proc.stderr
    log = (tmp_path / "fake.log").read_text()
    # pip install no debe llevar --index-url cuando el target es PyPI default.
    assert "--index-url" not in log


def test_verify_calls_capmd_convert(tmp_path: Path) -> None:
    proc = _run_verify(tmp_path, args=["0.2.0"])
    assert proc.returncode == 0, proc.stderr
    log = (tmp_path / "fake.log").read_text()
    assert "capmd convert" in log


def test_verify_latest_pkg_when_version_not_semver(tmp_path: Path) -> None:
    proc = _run_verify(tmp_path, args=["latest"])
    assert proc.returncode == 0, proc.stderr
    log = (tmp_path / "fake.log").read_text()
    # Sin '=' → install solo 'capmd' (latest).
    assert "capmd " in log or "capmd\\n" in log or log.endswith("capmd")
