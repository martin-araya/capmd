"""Tests for PyPI metadata in pyproject.toml (J4).

PyPI usa:
- `dependencies` para resolver el entorno del usuario.
- `[project.scripts]` para registrar entry points como `capmd`.
- `[project.urls]` para el sidebar de la pagina.
- `readme` para la long-description.

Estos tests verifican que el metadata PyPI-critico esta presente.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def pyproject() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_markitdown_declared_as_runtime_dependency(pyproject: dict[str, object]) -> None:
    """markitdown debe estar en dependencies (J4: no vendorizar)."""
    deps = pyproject["project"]["dependencies"]
    markitdown_deps = [d for d in deps if d.startswith("markitdown")]
    assert len(markitdown_deps) >= 1, (
        "markitdown debe estar declarado como runtime dependency (no vendorizar)"
    )
    # Los extras de markitdown cubren pdf, docx, pptx, xlsx (los formatos que capmd acepta).
    md_dep = markitdown_deps[0]
    for ext in ("pdf", "docx", "pptx", "xlsx"):
        assert ext in md_dep, f"markitdown dep debe incluir el extra '{ext}' (got: {md_dep!r})"


def test_capmd_entry_point_declared(pyproject: dict[str, object]) -> None:
    """El entry point `capmd = "capmd.cli:app"` debe estar en [project.scripts]."""
    scripts = pyproject["project"].get("scripts", {})
    assert scripts.get("capmd") == "capmd.cli:app", (
        f"entry point 'capmd' debe ser 'capmd.cli:app' (got: {scripts.get('capmd')!r})"
    )


def test_readme_path_resolves(pyproject: dict[str, object]) -> None:
    """`readme = "README.md"` debe apuntar a un archivo real (PyPI renderiza este como long-description)."""
    readme = pyproject["project"].get("readme")
    assert readme is not None, "pyproject.toml debe declarar `readme`"
    assert (REPO_ROOT / readme).is_file(), f"`readme = {readme!r}` no resuelve a un archivo"


def test_project_urls_populated(pyproject: dict[str, object]) -> None:
    """[project.urls] debe tener al menos Homepage + Issues (PyPI sidebar los muestra)."""
    urls = pyproject["project"].get("urls", {})
    assert urls.get("Homepage"), "Falta [project.urls].Homepage"
    assert urls.get("Issues"), "Falta [project.urls].Issues"


def test_project_urls_changelog_present(pyproject: dict[str, object]) -> None:
    """J3 introdujo el Changelog URL; J4 debe preservarlo (PyPI sidebar link)."""
    urls = pyproject["project"].get("urls", {})
    assert urls.get("Changelog"), "Falta [project.urls].Changelog (agregado en J3)"


def test_project_urls_source_present(pyproject: dict[str, object]) -> None:
    """J4 agrega [project.urls].Source para que PyPI linkee al repo."""
    urls = pyproject["project"].get("urls", {})
    assert urls.get("Source"), "Falta [project.urls].Source (agregado en J4)"


def test_classifiers_include_python_implementation(pyproject: dict[str, object]) -> None:
    """J4 agrega el classifier `Implementation :: CPython`."""
    classifiers = pyproject["project"].get("classifiers", [])
    assert "Programming Language :: Python :: Implementation :: CPython" in classifiers


def test_classifiers_python_versions(pyproject: dict[str, object]) -> None:
    """Las versiones de Python declaradas matchean lo que el repo soporta."""
    classifiers = pyproject["project"].get("classifiers", [])
    for minor in ("3.10", "3.11", "3.12"):
        expected = f"Programming Language :: Python :: {minor}"
        assert expected in classifiers, f"Falta classifier {expected!r}"


def test_requires_python_minimum(pyproject: dict[str, object]) -> None:
    """`requires-python = ">=3.10"` es la convencion del repo."""
    requires = pyproject["project"].get("requires-python")
    assert requires is not None and re.match(r"^>=3\.\d+", requires), (
        f"requires-python debe ser >=3.X (got: {requires!r})"
    )


def test_sdist_artifact_includes(pyproject: dict[str, object]) -> None:
    """El sdist debe incluir pyproject.toml + README + roadmap (metadata)."""
    sdist = pyproject.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("sdist", {})
    include = sdist.get("include", [])
    for required in ("README.md", "pyproject.toml"):
        assert required in include, (
            f"sdist include debe contener {required!r} para que PyPI renderice el long-description"
        )
