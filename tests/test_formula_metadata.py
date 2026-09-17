"""Tests de la fórmula Homebrew `Formula/capmd.rb` (I4).

Cubre la estructura mínima esperada por Homebrew:

- ``class Capmd < Formula``
- ``desc`` no vacío
- ``homepage`` apuntando al repo público
- ``license`` declarado
- ``url`` apuntando a un release tag (vX.Y.Z) en GitHub
- ``sha256`` válido (64 hex chars)
- ``depends_on "python@3.12"``
- Bloque ``bottle do ... end`` presente
- Bloque ``test do ... end`` con al menos un assert
- ``virtualenv_install_with_resources`` en el método ``install``
- Al menos un ``resource`` declarado con url + sha256

Los tests que ejecutan ``brew audit`` o interactúan con el toolchain real
están skipped si ``brew`` no está disponible o falla al inicializarse (en
este sandbox Homebrew se rompe por un gem conflict que es ortogonal a
la fórmula).

Para correr ``brew audit`` localmente::

    brew audit --strict --new ./Formula/capmd.rb
    brew style ./Formula/capmd.rb
    brew test ./Formula/capmd.rb
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORMULA = ROOT / "Formula" / "capmd.rb"


def _formula_text() -> str:
    return FORMULA.read_text(encoding="utf-8")


def _ruby_syntax() -> None:
    """Chequeo de sintaxis Ruby via el binario `ruby` del sistema."""
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("ruby no está instalado")
    proc = subprocess.run(
        [ruby, "-c", str(FORMULA)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"Formula/capmd.rb tiene errores de sintaxis: {proc.stderr}"
    )


def test_formula_parses_as_valid_ruby() -> None:
    _ruby_syntax()


def test_formula_class_declares_inherits_from_formula() -> None:
    text = _formula_text()
    assert re.search(r"^class\s+Capmd\s*<\s*Formula\b", text, re.MULTILINE), (
        "Falta `class Capmd < Formula` al inicio del archivo"
    )


def test_formula_desc_is_non_empty() -> None:
    text = _formula_text()
    m = re.search(r'^\s*desc\s+"([^"]+)"', text, re.MULTILINE)
    assert m, "Falta `desc` con una descripción corta"
    assert len(m.group(1)) > 10, f"`desc` demasiado corto: {m.group(1)!r}"


def test_formula_homepage_points_to_official_repo() -> None:
    text = _formula_text()
    m = re.search(r'^\s*homepage\s+"([^"]+)"', text, re.MULTILINE)
    assert m, "Falta `homepage`"
    assert "github.com/martin-araya/capmd" in m.group(1)


def test_formula_license_declared() -> None:
    text = _formula_text()
    assert re.search(r'^\s*license\s+"[^"]+"', text, re.MULTILINE), (
        "Falta `license` (debería ser MIT, igual que pyproject.toml)"
    )


def test_formula_url_points_to_github_release() -> None:
    text = _formula_text()
    m = re.search(r'^\s*url\s+"([^"]+)"', text, re.MULTILINE)
    assert m, "Falta `url`"
    url = m.group(1)
    assert "github.com/martin-araya/capmd" in url
    assert "/archive/refs/tags/" in url, (
        f"La `url` debe apuntar a un tarball de release, no a HEAD: {url}"
    )


def test_formula_sha256_is_well_formed() -> None:
    text = _formula_text()
    m = re.search(r'^\s*sha256\s+"([a-fA-F0-9]+)"', text, re.MULTILINE)
    assert m, "Falta `sha256`"
    sha = m.group(1)
    assert len(sha) == 64, f"sha256 debe tener 64 hex chars (got {len(sha)}): {sha}"
    assert re.fullmatch(r"[0-9a-f]{64}", sha), f"sha256 no es hex puro: {sha}"


def test_formula_current_sha256_matches_sdist() -> None:
    """El sha256 declarado debe matchear el sdist actual (si está commiteado)."""
    text = _formula_text()
    m = re.search(r'^\s*url\s+"([^"]+)"', text, re.MULTILINE)
    assert m
    declared = re.search(r'^\s*sha256\s+"([a-fA-F0-9]+)"', text, re.MULTILINE)
    assert declared

    # Si el tarball todavía no existe localmente, no validamos (e.g. primer
    # tag aún no creado). El maintainer corre `scripts/release.sh` para
    # generar la primera botella con sha256 fresco.
    version_match = re.search(r"/tags/v([0-9.]+)\.tar\.gz", m.group(1))
    if version_match is None:
        pytest.skip("URL no apunta a un tag semver conocido")
    version = version_match.group(1)
    sdist = ROOT / "dist" / f"capmd-{version}.tar.gz"
    if not sdist.exists():
        pytest.skip(
            f"{sdist} no existe; `release.sh` lo genera antes de hacer el tag"
        )
    import hashlib

    digest = hashlib.sha256(sdist.read_bytes()).hexdigest()
    assert digest == declared.group(1), (
        f"sha256 declarado ({declared.group(1)}) no coincide con el de "
        f"{sdist} ({digest}). Re-corré `scripts/release.sh {version}`."
    )


def test_formula_depends_on_python_3_12() -> None:
    text = _formula_text()
    assert re.search(r'^\s*depends_on\s+"python@3\.12"', text, re.MULTILINE), (
        "Falta `depends_on \"python@3.12\"`; capmd requiere Python ≥ 3.10 y "
        "macOS trae 3.9"
    )


def test_formula_uses_virtualenv_install() -> None:
    text = _formula_text()
    m = re.search(r"def\s+install\b(.*?)^\s*end\b", text, re.MULTILINE | re.DOTALL)
    assert m, "Falta el método `install`"
    body = m.group(1)
    assert "virtualenv_install" in body, (
        "El método install debe usar `virtualenv_install_with_resources` "
        "(patrón estándar de Homebrew Python formulae)"
    )


def test_formula_declares_at_least_one_resource() -> None:
    text = _formula_text()
    n = len(re.findall(r'^\s*resource\s+"[^"]+"\s+do\b', text, re.MULTILINE))
    assert n >= 9, (
        f"Se esperan al menos 9 resources (9 deps de pyproject.toml), "
        f"encontré {n}"
    )


def test_formula_resources_have_url_and_sha256() -> None:
    text = _formula_text()
    # Cada resource `do ... end` debe tener un url y sha256 adentro
    for m in re.finditer(
        r'resource\s+"([^"]+)"\s+do\b(.*?)\bend\b', text, re.DOTALL
    ):
        name = m.group(1)
        body = m.group(2)
        assert 'url "' in body, f"resource {name!r} sin `url`"
        assert 'sha256 "' in body, f"resource {name!r} sin `sha256`"
        sha_m = re.search(r'sha256\s+"([a-fA-F0-9]+)"', body)
        assert sha_m and len(sha_m.group(1)) == 64, (
            f"resource {name!r} tiene sha256 mal formado: {sha_m.group(1) if sha_m else '?'}"
        )


def test_formula_has_bottle_block() -> None:
    text = _formula_text()
    assert re.search(r"^\s*bottle\s+do\b", text, re.MULTILINE), (
        "Falta el bloque `bottle do … end` (las botellas las llena brew bottle"
        " en release-time)"
    )


def test_formula_has_test_block_with_assertion() -> None:
    text = _formula_text()
    m = re.search(r"test\s+do\b(.*?)\bend\b", text, re.DOTALL)
    assert m, "Falta el bloque `test do … end`"
    body = m.group(1)
    assert "assert_match" in body, "El bloque `test` debe tener al menos un assert_match"


def test_formula_test_block_references_real_subcommands() -> None:
    """Los smoke tests deben validar `--version` y `convert` (no nombres arbitrarios)."""
    text = _formula_text()
    test_m = re.search(r"test\s+do\b(.*?)\bend\b", text, re.DOTALL)
    assert test_m
    body = test_m.group(1)
    assert "--version" in body, "El test no verifica `capmd --version`"
    assert "--help" in body, "El test no verifica `capmd --help`"
    assert "convert" in body, "El test no verifica el subcomando `convert`"


# ---------------------------------------------------------------------------
# Integración con `brew` (live; skipped si brew no está disponible o falla)
# ---------------------------------------------------------------------------


def _brew_available() -> bool:
    brew = shutil.which("brew")
    if not brew:
        return False
    # El binario `brew` puede estar en PATH pero estar roto a nivel Ruby
    # (gem conflict, etc.). Hacemos un smoke command que internamente
    # requiere que `brew audit --help` funcione — si falla por JSON gem
    # conflict u otro error ortogonal a la fórmula, skipeamos.
    try:
        proc = subprocess.run(
            [brew, "audit", "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return (
        proc.returncode == 0
        and "default_sort_keys_proc" not in proc.stderr
        and "NoMethodError" not in proc.stderr
    )


@pytest.mark.skipif(
    not _brew_available(),
    reason="brew no está disponible o falla al inicializarse en este entorno",
)
def test_brew_audit_passes() -> None:
    proc = subprocess.run(
        ["brew", "audit", "--strict", "./Formula/capmd.rb"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    # brew audit suele llamar a networking. Si falla por red, skip; si falla
    # por estilo/sintaxis, fail.
    if "Could not resolve" in proc.stderr or "Network" in proc.stderr:
        pytest.skip(f"brew audit sin red: {proc.stderr[:200]}")
    assert proc.returncode == 0, (
        f"`brew audit --strict` falló:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


@pytest.mark.skipif(
    not _brew_available(),
    reason="brew no está disponible o falla al inicializarse en este entorno",
)
def test_brew_style_passes() -> None:
    proc = subprocess.run(
        ["brew", "style", "./Formula/capmd.rb"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"`brew style` reportó issues:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
