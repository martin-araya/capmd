"""Verifica que ``capmd`` se autoregistra como plugin de markitdown."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from importlib.metadata import entry_points
from pathlib import Path

import pytest

import capmd
from capmd.markitdown_plugin import (
    PLUGIN_NAME,
    CleanersMarkItDownPlugin,
    MarkdownCleanerConverter,
)

PLUGIN_ENTRYPOINT = "capmd.markitdown_plugin:CleanersMarkItDownPlugin"


def _find_markitdown_cli():
    """Devuelve la ruta al binario ``markitdown`` o None si no está disponible.

    Primero busca en ``$PATH`` y, si no, mira dentro del ``.venv`` del repo.
    """
    found = shutil.which("markitdown")
    if found:
        return found
    repo_venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "markitdown"
    if repo_venv.is_file():
        return str(repo_venv)
    return None


def _load_capmd_plugin_entry_point():
    """Devuelve el entry-point ``capmd-cleaners`` o None si no está registrado."""
    eps = entry_points(group="markitdown.plugin")
    for ep in eps:
        if ep.name == PLUGIN_NAME:
            return ep
    return None


def test_entry_point_is_registered_under_markitdown_plugin_group() -> None:
    """El grupo ``markitdown.plugin`` debe contener un entry-point ``capmd-cleaners``."""
    ep = _load_capmd_plugin_entry_point()
    assert ep is not None, (
        f"No se encontró entry-point '{PLUGIN_NAME}' en el grupo 'markitdown.plugin'. "
        "Asegurate de que pyproject.toml tenga el bloque "
        "[project.entry-points.\"markitdown.plugin\"]."
    )
    assert ep.value == PLUGIN_ENTRYPOINT


def test_plugin_class_metadata() -> None:
    """Los metadatos del plugin reflejan el paquete capmd."""
    assert CleanersMarkItDownPlugin.name == PLUGIN_NAME
    assert CleanersMarkItDownPlugin.version == capmd.__version__
    assert CleanersMarkItDownPlugin.enabled is True
    assert isinstance(CleanersMarkItDownPlugin.description, str)
    assert CleanersMarkItDownPlugin.description  # no vacía


def test_register_converters_uses_classmethod() -> None:
    """``register_converters`` se puede invocar sobre la clase (sin instanciar)."""
    assert isinstance(CleanersMarkItDownPlugin.__dict__["register_converters"], classmethod)


def test_register_converters_registers_converter() -> None:
    """Al invocarlo, queda un ``MarkdownCleanerConverter`` registrado en MarkItDown."""
    from markitdown import MarkItDown

    md = MarkItDown(enable_plugins=False)
    initial_count = len(md._converters)  # type: ignore[attr-defined]

    CleanersMarkItDownPlugin.register_converters(md)

    # El converter quedó registrado.
    assert len(md._converters) == initial_count + 1  # type: ignore[attr-defined]
    registered = md._converters[0].converter  # type: ignore[attr-defined]
    assert isinstance(registered, MarkdownCleanerConverter)


def test_markitdown_list_plugins_subprocess() -> None:
    """``markitdown --list-plugins`` muestra el plugin capmd-cleaners."""
    markitdown_cli = _find_markitdown_cli()
    if markitdown_cli is None:
        pytest.skip("markitdown CLI no disponible en el venv")

    # Limpia variables que puedan interferir con el subprocess de markitdown.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}

    result = subprocess.run(
        [markitdown_cli, "--list-plugins"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert PLUGIN_NAME in result.stdout
    assert PLUGIN_ENTRYPOINT in result.stdout

    # El output debe tener el formato esperado: ``  * name<TAB/space>(package: value)``.
    pattern = rf"\*\s+{PLUGIN_NAME}[ \t]+\(package:[ \t]+{re.escape(PLUGIN_ENTRYPOINT)}\)"
    assert re.search(pattern, result.stdout), (
        f"linea inesperada en --list-plugins:\n{result.stdout}"
    )


def test_plugin_importable_from_external_call() -> None:
    """El módulo es importable y expone los símbolos públicos esperados."""
    import capmd.markitdown_plugin as mod

    assert hasattr(mod, "CleanersMarkItDownPlugin")
    assert hasattr(mod, "MarkdownCleanerConverter")
    assert hasattr(mod, "PLUGIN_NAME")
