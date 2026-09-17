"""Tests del install como tool (I1).

Verifica que `capmd` se puede empaquetar como wheel, que el entry point queda
registrado y que el binario corre sin un venv activo. Sin red ni PyPI: el wheel
se construye desde el source local.
"""

from __future__ import annotations

import email
import importlib
import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _build_wheel(tmp_path: Path) -> Path:
    """Build del wheel via `python -m build` en tmp_path/dist."""
    dist = tmp_path / "dist"
    dist.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr
        if "No module named build" in stderr:
            pytest.skip("`build` no está instalado; `pip install build` para correr este test")
        pytest.fail(f"`python -m build --wheel` falló:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1, f"se esperaba 1 wheel, encontré {len(wheels)}: {wheels}"
    return wheels[0]


def test_pyproject_entry_point_resolves() -> None:
    """El entry point `capmd = "capmd.cli:app"` está declarado y resuelve a un callable."""
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)

    scripts = data["project"]["scripts"]
    assert scripts["capmd"] == "capmd.cli:app", (
        f"entry point inesperado: {scripts.get('capmd')!r}"
    )

    mod = importlib.import_module("capmd.cli")
    target = scripts["capmd"].split(":")[1]
    app = getattr(mod, target)
    assert callable(app), f"capmd.cli:{target} no es callable"


def test_wheel_contains_clean_data(tmp_path: Path) -> None:
    """El wheel incluye los datos de cleaners (force-include debe seguir vigente)."""
    wheel = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        data_files = [n for n in names if n.startswith("capmd/clean/data/")]
        assert data_files, (
            "el wheel no incluye capmd/clean/data/*; revisar `tool.hatch.build.targets.wheel.force-include`"
        )
        # spot-check: al menos uno de los wordlists conocidos
        assert any(n.endswith("words_en.txt") for n in data_files), (
            f"falta words_en.txt en el wheel; archivos: {data_files}"
        )


def test_wheel_metadata_urls_not_placeholder(tmp_path: Path) -> None:
    """METADATA del wheel no contiene el placeholder `<tu-usuario>`."""
    wheel = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel) as zf:
        metadata_name = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")),
            None,
        )
        assert metadata_name is not None, "no se encontró METADATA en el wheel"
        raw = zf.read(metadata_name).decode("utf-8")

    msg = email.message_from_string(raw)
    assert "<tu-usuario>" not in raw, (
        f"METADATA todavía contiene el placeholder <tu-usuario>: {raw[:500]}"
    )

    home_page = msg.get("Home-page") or ""
    project_urls = msg.get_all("Project-URL") or []
    urls_blob = "\n".join([home_page, *project_urls])
    assert "capmd" in urls_blob, f"METADATA no menciona capmd en URLs: {urls_blob!r}"


@pytest.mark.skipif(sys.platform == "win32", reason="VIRTUAL_ENV handling difiere en Windows")
def test_entry_point_runs_without_active_venv(tmp_path: Path) -> None:
    """Test literal del roadmap I1.

    Instala el wheel en un venv efímero, luego corre `capmd --help` desde un
    subproceso con VIRTUAL_ENV vacío y PATH apuntando solo al binario del venv
    (no al project venv).
    """
    wheel = _build_wheel(tmp_path)

    venv_dir = tmp_path / "capmd_venv"
    venv.create(venv_dir, with_pip=True, clear=True)

    venv_python = venv_dir / "bin" / "python"
    venv_capmd = venv_dir / "bin" / "capmd"

    # Instalar el wheel dentro del venv.
    proc = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"pip install del wheel falló:\n{proc.stdout}\n{proc.stderr}")
    assert venv_capmd.exists(), f"el binario capmd no se creó en {venv_capmd}"

    # PATH con solo el bin dir del venv: garantiza que NO se resuelva un `capmd`
    # desde el project venv o del sistema.
    bin_dir = str(venv_dir / "bin")
    env = {
        **os.environ,
        "PATH": bin_dir,
        "VIRTUAL_ENV": "",
        "PYTHONHOME": "",
    }
    proc = subprocess.run(
        [str(venv_capmd), "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, (
        f"`capmd --help` salió con {proc.returncode}:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    out = proc.stdout + proc.stderr
    assert "convert" in out, (
        f"`capmd --help` no menciona el subcomando `convert`; output:\n{out}"
    )

    # `capmd version` también tiene que funcionar.
    proc = subprocess.run(
        [str(venv_capmd), "version"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"`capmd version` salió con {proc.returncode}"
    assert proc.stdout.strip(), "capmd version no imprimió nada"


def test_pipx_compatible_metadata(tmp_path: Path) -> None:
    """METADATA coherente con `pipx install` y `uv tool install`.

    Requisitos mínimos que pipx/uv tool validan al instalar:
      - `Name` y `Version` presentes
      - `Requires-Python` presente y bien formado
      - entry point `capmd` apunta a módulo:attr
    """
    from packaging.specifiers import SpecifierSet

    wheel = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel) as zf:
        dist_info = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        entry_points_name = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt")),
            None,
        )
        raw = zf.read(dist_info).decode("utf-8")
        entry_points_text = (
            zf.read(entry_points_name).decode("utf-8") if entry_points_name else ""
        )

    msg = email.message_from_string(raw)
    assert msg.get("Name") == "capmd"
    assert msg.get("Version"), "falta Version en METADATA"

    req_py = msg.get("Requires-Python")
    assert req_py is not None, "falta Requires-Python en METADATA"
    spec = SpecifierSet(req_py)
    assert spec.contains(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"), (
        f"Requires-Python {req_py!r} no satisface {sys.version}"
    )

    assert entry_points_text, "no hay entry_points.txt en el wheel"
    console_entries = [
        line.strip()
        for line in entry_points_text.splitlines()
        if line.strip().startswith("capmd") and "=" in line
    ]
    assert console_entries, f"no hay entry point `capmd` en entry_points.txt:\n{entry_points_text}"
    value = console_entries[0].split("=", 1)[1].strip()
    assert value == "capmd.cli:app", f"entry point inesperado: {value!r}"
