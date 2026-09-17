"""Tests for scripts/bump-version.sh (J3).

Mockeamos `git-cliff` (no asumimos que esté instalado en la CI del proyecto)
y verificamos que el script:
- Pasa de v0.1.0 a v0.2.0 cuando git-cliff lo sugiere.
- Detecta cuando no hay cambio.
- Falla con exit != 0 si git-cliff no está en PATH o devuelve una versión inválida.
- Falla con exit != 0 si pyproject.toml no tiene un `version = "..."` parseable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUMP_SCRIPT = REPO_ROOT / "scripts" / "bump-version.sh"


def _run_bump(
    tmp_path: Path,
    *,
    git_cliff_output: str | None = None,
    with_fake_cliff: bool = True,
    pyproject: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run scripts/bump-version.sh inside ``tmp_path``.

    By default copies the repo's real pyproject.toml into tmp_path so the
    script's sed is observable. Pass ``pyproject`` to override (e.g. for
    the "missing version line" case).
    """
    if pyproject is None:
        shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    else:
        (tmp_path / "pyproject.toml").write_text(pyproject)

    env = {**os.environ}

    if with_fake_cliff and git_cliff_output is not None:
        fake_dir = tmp_path / "_bin"
        fake_dir.mkdir()
        (fake_dir / "git-cliff").write_text(
            "#!/usr/bin/env sh\n"
            f"echo '{git_cliff_output}'\n"
        )
        (fake_dir / "git-cliff").chmod(0o755)
        env["PATH"] = str(fake_dir) + ":" + env.get("PATH", "")

    return subprocess.run(
        ["bash", str(BUMP_SCRIPT), str(tmp_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_bump_version_no_cliff_exits_nonzero(tmp_path: Path) -> None:
    """Sin git-cliff en PATH, el script aborta con exit code 1."""
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        ["bash", str(BUMP_SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "git-cliff" in proc.stderr.lower()


def test_bump_version_invalid_cliff_output(tmp_path: Path) -> None:
    """git-cliff que devuelve algo no-SemVer → exit 1."""
    proc = _run_bump(tmp_path, git_cliff_output="not-semver")
    assert proc.returncode != 0
    assert "no parece semver" in proc.stderr.lower()


def test_bump_version_no_change_exits_zero(tmp_path: Path) -> None:
    """Si git-cliff devuelve la versión actual, exit 0 sin patchear nada."""
    proc = _run_bump(tmp_path, git_cliff_output="0.1.0")
    assert proc.returncode == 0
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.1.0"' in text


def test_bump_version_patches_pyproject(tmp_path: Path) -> None:
    """git-cliff sugiere v0.2.0 → pyproject.toml queda v0.2.0."""
    proc = _run_bump(tmp_path, git_cliff_output="0.2.0")
    assert proc.returncode == 0
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in text


def test_bump_version_preserves_other_lines(tmp_path: Path) -> None:
    """El sed solo cambia la línea de versión, no toca otras."""
    proc = _run_bump(tmp_path, git_cliff_output="0.2.0")
    assert proc.returncode == 0
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'name = "capmd"' in text
    assert "markitdown" in text
    assert "typer" in text
    assert 'version = "0.2.0"' in text
    assert not (tmp_path / "pyproject.toml.bak").exists()
    assert not (tmp_path / "pyproject.toml.tmp").exists()


def test_bump_version_missing_version_line(tmp_path: Path) -> None:
    """pyproject.toml sin `version = ...` → grep falla → exit 1."""
    proc = _run_bump(
        tmp_path,
        git_cliff_output="0.2.0",
        pyproject="[project]\nname = 'capmd'\n",
    )
    assert proc.returncode != 0

