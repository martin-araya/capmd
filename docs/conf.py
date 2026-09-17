"""Sphinx configuration for capmd docs.

Build with: ``make -C docs html`` (or ``sphinx-build docs docs/_build/html``).

The site is generated as static HTML under ``docs/_build/html/`` and is
served via GitHub Pages (or read locally with ``make -C docs serve``).
The repo intentionally does NOT use GH Actions (project rule), so the
build is triggered locally by the maintainer and the ``_build/`` output
is not committed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `capmd` importable so autodoc can extract docstrings.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

project = "capmd"
author = "capmd contributors"
copyright = f"2026, {author}"

# Read the version dynamically from pyproject.toml so docs/source stay in sync.
import tomllib

with (REPO_ROOT / "pyproject.toml").open("rb") as f:
    _PYPROJECT = tomllib.load(f)

version = _PYPROJECT["project"]["version"]
release = version

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",       # Google/NumPy-style docstrings
    "sphinx.ext.viewcode",        # [source] link in HTML
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",            # TODO blocks in .md
    "sphinx_copybutton",
    "sphinxext.opengraph",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "modules/*.md"]

# -- HTML output ---------------------------------------------------------
html_theme = "furo"
html_title = f"capmd {version}"
html_static_path = ["_static"]
html_favicon = None  # opcional: capmd.svg
html_theme_options = {
    "navigation_with_indexes": True,
    "top_of_page_button": "edit",
    "source_repository": "https://github.com/martin-araya/capmd",
    "source_branch": "main",
    "source_directory": "docs/",
}

# -- MyST (Markdown) extensions -----------------------------------------
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "dollarmath",
    "smartquotes",
    "replacements",
    "tasklist",
]
myst_heading_anchors = 3
myst_dmath_double_inline = True

# -- Autodoc -------------------------------------------------------------
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "show-inheritance-diagram": False,  # requiere graphviz; desactivado
    "exclude-members": "__init__",
}
autodoc_class_signature = "separated"
autodoc_pydantic_model_show_field_summary = False

# -- Intersphinx ---------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "typer": ("https://typer.tiangolo.com/", None),
    "rich": ("https://rich.readthedocs.io/en/stable/", None),
    "pypdf": ("https://pypdf.readthedocs.io/en/stable/", None),
    "pypdfium2": ("https://pypdfium2.readthedocs.io/en/stable/", None),
}

# -- OpenGraph (social cards) -------------------------------------------
ogp_site_url = "https://capmd.readthedocs.io/"  # change if hosting elsewhere
ogp_image = "_static/og-image.png"  # opcional
ogp_description_length = 200
ogp_type = "website"

# -- Todo extension ------------------------------------------------------
todo_include_todos = True
todo_link_only = False
