"""Tests de los scripts de release (I4).

Cubre la estructura de ``scripts/release.sh`` y ``scripts/build-bottles.sh``
sin invocarlos de verdad (eso sería destructivo contra el repo + requeriria
``brew`` + ``gh`` autenticado + acceso de push al repo).

Lo que se valida acá:

- Shebang correcto + ejecutable.
- Etapas mínimas del release.sh están presentes (pytest, ruff, build,
  sdist sha256, Formula patch, build-bottles, commit, tag, push, gh release).
- build-bottles.sh detecta target arm64_sonoma/sequoia, valida brew,
  maneja error si brew falta.
- Los strings críticos que el script escribe a stdout están documentados.
"""

from __future__ import annotations

import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SH = ROOT / "scripts" / "release.sh"
BUILD_BOTTLES_SH = ROOT / "scripts" / "build-bottles.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Permisos + shebang
# ---------------------------------------------------------------------------


def _executable(path: Path) -> None:
    assert path.exists(), f"{path} no existe"
    mode = path.stat().st_mode
    assert mode & stat.S_IXUSR, f"{path} no es ejecutable (chmod +x)"


def test_release_sh_is_executable() -> None:
    _executable(RELEASE_SH)


def test_build_bottles_sh_is_executable() -> None:
    _executable(BUILD_BOTTLES_SH)


def test_release_sh_has_bash_shebang() -> None:
    first = _text(RELEASE_SH).splitlines()[0]
    assert first.startswith("#!/usr/bin/env bash"), first


def test_build_bottles_sh_has_bash_shebang() -> None:
    first = _text(BUILD_BOTTLES_SH).splitlines()[0]
    assert first.startswith("#!/usr/bin/env bash"), first


# ---------------------------------------------------------------------------
# release.sh: etapas críticas
# ---------------------------------------------------------------------------


def test_release_sh_validates_semver_argument() -> None:
    text = _text(RELEASE_SH)
    # regex simple de semver X.Y.Z, en bash =^[0-9]+\.[0-9]+\.[0-9]+$
    assert "VERSION=" in text
    assert "=~ ^" in text, (
        "release.sh debe validar que el argumento es semver X.Y.Z "
        "(buscamos un regex `=~ ^X.Y.Z` literal en bash)"
    )
    assert "Uso:" in text or "Usage:" in text, (
        "release.sh debe tener mensaje de uso si no se pasa argumento"
    )


def test_release_sh_rejects_dirty_worktree() -> None:
    text = _text(RELEASE_SH)
    assert "git status --porcelain" in text, (
        "release.sh debe chequear que el working tree está limpio antes de "
        "etiquetar"
    )


def test_release_sh_requires_gh_authenticated() -> None:
    text = _text(RELEASE_SH)
    assert "gh auth status" in text, (
        "release.sh debe exigir que `gh` esté autenticado antes de hacer "
        "cualquier cosa destructiva"
    )


def test_release_sh_runs_pytest_before_release() -> None:
    text = _text(RELEASE_SH)
    assert "pytest" in text, "release.sh debe correr pytest antes de tag/push"
    assert "tests" in text


def test_release_sh_runs_ruff_check() -> None:
    text = _text(RELEASE_SH)
    assert "ruff" in text, (
        "release.sh debe correr `ruff check` antes de tag/push"
    )


def test_release_sh_builds_wheel_and_sdist() -> None:
    text = _text(RELEASE_SH)
    assert "python3 -m build" in text
    assert "--sdist" in text
    assert "--wheel" in text


def test_release_sh_computes_sdist_sha256() -> None:
    text = _text(RELEASE_SH)
    assert "shasum" in text, (
        "release.sh debe calcular el sha256 del sdist"
    )
    assert "awk '{print $1}'" in text or "awk \"{print $1}\"" in text


def test_release_sh_patches_formula_url_and_sha() -> None:
    text = _text(RELEASE_SH)
    assert "Formula/capmd.rb" in text, (
        "release.sh debe patchear Formula/capmd.rb con el sha256 fresco"
    )
    # El bloque de patch usa regex vía python (`python3 - <<EOF`)
    assert "re.sub" in text
    assert "sha256" in text


def test_release_sh_invokes_build_bottles() -> None:
    text = _text(RELEASE_SH)
    assert "scripts/build-bottles.sh" in text, (
        "release.sh debe invocar build-bottles.sh para producir las botellas"
    )


def test_release_sh_creates_git_tag_and_pushes() -> None:
    text = _text(RELEASE_SH)
    assert "git tag" in text
    assert "git push" in text


def test_release_sh_creates_github_release_with_assets() -> None:
    text = _text(RELEASE_SH)
    assert "gh release create" in text, (
        "release.sh debe invocar `gh release create` (no `gh release upload`)"
    )
    assert "bottle.tar.gz" in text, (
        "release.sh debe subir las .bottle.tar.gz como assets del release"
    )


def test_release_sh_handles_release_notes() -> None:
    text = _text(RELEASE_SH)
    assert "--notes-file" in text or "-F " in text, (
        "release.sh debe aceptar/auto-generar las notas del release"
    )


# ---------------------------------------------------------------------------
# build-bottles.sh: etapas críticas
# ---------------------------------------------------------------------------


def test_build_bottles_requires_brew() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert "command -v brew" in text, (
        "build-bottles.sh debe abortar si brew no está instalado"
    )


def test_build_bottles_refuses_non_arm64() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert 'arm64' in text, "build-bottles.sh debe target arm64"
    # Rechaza explícitamente x86_64 (chequeando que ARCH != "arm64" produce error)
    assert '[ "$ARCH" != "arm64" ]' in text or '!= "arm64"' in text, (
        "build-bottles.sh debe rechazar arquitecturas != arm64"
    )


def test_build_bottles_targets_sonoma_and_sequoia() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert "arm64_sonoma" in text
    assert "arm64_sequoia" in text


def test_build_bottles_uses_brew_root_url_with_version() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert "releases/download/v" in text, (
        "build-bottles.sh debe configurar el --root-url apuntando a GitHub "
        "Releases del release actual"
    )
    assert "ROOT_URL=" in text


def test_build_bottles_runs_brew_audit() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert "brew audit" in text, (
        "build-bottles.sh debe correr `brew audit --strict --new` antes de "
        "gastar tiempo en la bottle"
    )


def test_build_bottles_uses_brew_bottle_command() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert "brew bottle" in text, (
        "build-bottles.sh debe invocar `brew bottle` para generar el "
        ".bottle.tar.gz + parche"
    )
    assert "--build-bottle" in text


def test_build_bottles_applies_patch_and_cleans_up() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert "capmd--bottle" in text, (
        "build-bottles.sh debe buscar el parche que emite `brew bottle`"
    )
    assert "Formula/capmd.rb" in text


def test_build_bottles_reads_version_from_pyproject() -> None:
    text = _text(BUILD_BOTTLES_SH)
    assert "pyproject.toml" in text
    assert 'version = "' in text or "version =" in text
    assert "VERSION=" in text or "version=" in text
