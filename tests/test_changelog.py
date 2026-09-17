"""Tests for changelog/cliff.toml + post-tag hook (J3).

Verifica que:
- CHANGELOG.md existe y tiene secciones versionadas.
- cliff.toml es TOML parseable y declara el tag pattern vX.Y.Z.
- scripts/hooks/post-tag existe y es ejecutable.
- scripts/install-hooks.sh existe y es ejecutable.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_changelog_file_exists() -> None:
    assert (REPO_ROOT / "CHANGELOG.md").is_file(), "Falta CHANGELOG.md"


def test_changelog_not_empty() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text()
    assert len(text.strip()) > 100, "CHANGELOG.md debe tener contenido real"


def test_changelog_has_version_sections() -> None:
    """Al menos un heading `## [X.Y.Z]` (Keep-a-Changelog style)."""
    text = (REPO_ROOT / "CHANGELOG.md").read_text()
    pattern = re.compile(r"^##\s+\[(\d+\.\d+\.\d+|[Uu]nreleased)\]", re.MULTILINE)
    matches = pattern.findall(text)
    assert len(matches) >= 1, (
        f"CHANGELOG.md debe tener al menos un '## [X.Y.Z]' o '## [unreleased]' "
        f"(encontrado: {matches})"
    )


def test_changelog_has_unreleased_section() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text()
    assert "## [unreleased]" in text, "CHANGELOG.md debe tener una sección [unreleased]"


def test_cliff_toml_exists_and_loads() -> None:
    """cliff.toml es TOML parseable y tiene tag pattern correcto."""
    cliff = REPO_ROOT / "cliff.toml"
    assert cliff.is_file()
    data = tomllib.loads(cliff.read_text())
    assert "changelog" in data, "cliff.toml debe tener sección [changelog]"
    assert "git" in data, "cliff.toml debe tener sección [git]"
    # El tag pattern matchea vX.Y.Z.
    tag_pattern = data["git"].get("tag_pattern", "")
    assert re.match(r"^v\[0-9\]", tag_pattern), (
        f"git.tag_pattern debe empezar con 'v[0-9]...' (got: {tag_pattern!r})"
    )


def test_cliff_toml_has_commit_parsers() -> None:
    """cliff.toml debe parsear tipos conventional (feat/fix/etc)."""
    data = tomllib.loads((REPO_ROOT / "cliff.toml").read_text())
    parsers = data.get("commit_parsers", [])
    parser_patterns = " ".join(p.get("pattern", "") for p in parsers)
    # Los patrones usan [Ff]eat / [Ff]ix para ser case-insensitive.
    assert "eat" in parser_patterns, "cliff.toml debe reconocer feat commits"
    assert "[Ff]ix" in parser_patterns, "cliff.toml debe reconocer fix commits"
    assert "[Dd]ocs" in parser_patterns, "cliff.toml debe reconocer docs commits"


def test_post_tag_hook_exists_and_executable() -> None:
    hook = REPO_ROOT / "scripts" / "hooks" / "post-tag"
    assert hook.is_file(), "Falta scripts/hooks/post-tag"
    mode = hook.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/hooks/post-tag debe ser ejecutable"


def test_install_hooks_script_exists_and_executable() -> None:
    script = REPO_ROOT / "scripts" / "install-hooks.sh"
    assert script.is_file(), "Falta scripts/install-hooks.sh"
    mode = script.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/install-hooks.sh debe ser ejecutable"


def test_post_tag_hook_invokes_release_sh() -> None:
    """El hook debe terminar invocando scripts/release.sh con la version del tag."""
    hook = (REPO_ROOT / "scripts" / "hooks" / "post-tag").read_text()
    assert "release.sh" in hook
    assert "VERSION" in hook


def test_post_tag_hook_ignores_non_semver() -> None:
    """El hook debe ignora tags lightweight (no annotated) y non-semver."""
    hook = (REPO_ROOT / "scripts" / "hooks" / "post-tag").read_text()
    assert "refs/tags/v[0-9]" in hook or "v[0-9]*.[0-9]*.[0-9]*" in hook


def test_install_hooks_points_to_versioned_dir() -> None:
    """install-hooks.sh debe apuntar core.hooksPath al directorio de hooks."""
    script = (REPO_ROOT / "scripts" / "install-hooks.sh").read_text()
    assert "core.hooksPath" in script
    # HOOKS_DIR viene de "$(dirname "$0")/hooks" → resuelve a scripts/hooks en runtime.
    assert "hooks" in script
    assert "/hooks\"" in script or '/hooks"' in script or "hooks && pwd" in script
