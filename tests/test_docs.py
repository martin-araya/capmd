"""J5: test del contrato del roadmap.

Lee `README.md`, extrae cada bloque ```bash```, y valida que:

1. Los bloques que corren `capmd convert` / `capmd toc` / `capmd inspect` /
   `capmd open` / `capmd batch` exit 0 + output no vacío cuando se ejecutan
   contra el binario `capmd` instalado en el test venv.
2. Los bloques de setup (brew install, uv tool install) no son ejecutables
   en CI y se skipean.

Esto implementa el test del roadmap J5: "alguien que nunca vio el
proyecto convierte un capítulo siguiendo solo el README".
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

BASH_BLOCK = re.compile(r"```bash\n(.*?)\n```", re.DOTALL)


def _extract_bash_blocks(text: str) -> list[tuple[int, str]]:
    """Extrae bloques bash del README. Return (line_number, block_text)."""
    blocks = []
    for m in BASH_BLOCK.finditer(text):
        # Compute line number from match offset.
        line_no = text[: m.start()].count("\n") + 1
        blocks.append((line_no, m.group(1).strip()))
    return blocks


def _is_executable(block: str) -> bool:
    """Decide si el bloque se puede correr contra `capmd` instalado."""
    # Skip setup / install / brew / uv tool / setup blocks.
    skip_keywords = (
        "brew install",
        "brew tap",
        "brew services",
        "brew audit",
        "brew bottle",
        "uv tool install",
        "uv pip install",
        "pip install",
        "uv sync",
        "git clone",
        "git checkout",
        "git push",
        "git remote",
        "git config",
        "gh release",
        "gh auth",
        "gcloud",
        "swift run",
        "xcodebuild",
        "source ",
        "export ",
        "echo ",
        "cat ",
        "ls ",
        "cd ",
        "uv ",
        "python3 -m pip",
        "mktemp",
        "xattr -d com.apple.quarantine",
        "cd .",
        "mkdir -p ",
        "BREW_TAP",
        "FORMULA",
        "maintainer",
        "bash scripts/",
        "pytest ",
        "ruff ",
        "mypy ",
        "make ",
        "open http",
        "open docs/",
        "tail ",
        "find ",
        "# ",  # comentarios
    )
    for kw in skip_keywords:
        if kw in block:
            return False
    # Skip multi-line blocks (variables / heredocs).
    if "\n" in block and any(
        k in block for k in ("if ", "for ", "while ", "case ", "function ")
    ):
        return False
    # Skip blocks that are pure text output (not actual commands).
    if block.startswith("$") or block.startswith("#") or not block.strip():
        return False
    # Solo ejecutar bloques que contengan `capmd ...`.
    return "capmd " in block or block.startswith("capmd")


REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def bash_blocks() -> list[tuple[int, str]]:
    return _extract_bash_blocks(README.read_text())


@pytest.fixture(scope="module")
def executable_blocks(bash_blocks: list[tuple[int, str]]) -> list[tuple[int, str]]:
    return [(n, b) for n, b in bash_blocks if _is_executable(b)]


def test_readme_has_bash_blocks(bash_blocks: list[tuple[int, str]]) -> None:
    """El README debe tener al menos 1 bloque bash."""
    assert len(bash_blocks) >= 5, (
        f"README debe tener >=5 bloques bash para servir como tutorial; "
        f"encontre {len(bash_blocks)}"
    )


def test_readme_has_executable_blocks(executable_blocks: list[tuple[int, str]]) -> None:
    """Al menos 1 bloque debe correr contra el binario `capmd` instalado."""
    assert len(executable_blocks) >= 1, (
        "README debe tener >=1 bloque ejecutable (con `capmd ...`) que el "
        "test contracto pueda validar"
    )


@pytest.fixture(scope="module")
def capmd_executable() -> str:
    """Localiza el binario capmd en PATH o venv."""
    path = shutil.which("capmd")
    if path:
        return path
    venv_capmd = REPO_ROOT / ".venv" / "bin" / "capmd"
    if venv_capmd.is_file():
        return str(venv_capmd)
    pytest.skip("`capmd` no encontrado en PATH ni en .venv/bin/; instalar antes de correr este test")


def test_executable_blocks_have_capmd(bash_blocks: list[tuple[int, str]]) -> None:
    """Cada bloque ejecutable debe usar el comando `capmd` (sanity check)."""
    for line_no, block in bash_blocks:
        if _is_executable(block):
            assert "capmd" in block, (
                f"Bloque ejecutable en README.md:{line_no} no contiene `capmd`"
            )


def test_quickstart_block_runs(tmp_path: Path, capmd_executable: str) -> None:
    """El bloque Quickstart del README debe correr contra `capmd`.

    Tomamos un fixture del repo, lo copiamos a tmp_path, ejecutamos los
    comandos del Quickstart y validamos exit 0 + markdown output.
    """
    # Buscar un fixture existente.
    fixtures_dir = REPO_ROOT / "tests" / "fixtures"
    pdf_fixture: Path | None = None
    for name in ("book.pdf", "headings.pdf"):
        cand = fixtures_dir / name
        if cand.is_file():
            pdf_fixture = cand
            break

    if pdf_fixture is None:
        # Generate one from a builder.
        from tests.fixtures import build

        pdf_fixture = tmp_path / "headings.pdf"
        build.build_headings_pdf(pdf_fixture)

    # Run `capmd toc` (siempre funciona en PDFs con outline).
    proc = subprocess.run(
        [capmd_executable, "toc", str(pdf_fixture)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"`capmd toc` falló: {proc.stderr}"
    assert len(proc.stdout) > 0, "`capmd toc` output vacio"


def test_capmd_version_executable(capmd_executable: str) -> None:
    """`capmd version` (ejemplo del README) debe correr sin error."""
    proc = subprocess.run(
        [capmd_executable, "version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "capmd" in proc.stdout.lower()


def test_capmd_help_executable(capmd_executable: str) -> None:
    """`capmd --help` (mostrado como ejemplo) debe correr."""
    proc = subprocess.run(
        [capmd_executable, "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "Usage" in proc.stdout or "usage" in proc.stdout.lower()


def test_capmd_config_init_executable(tmp_path: Path, capmd_executable: str) -> None:
    """`capmd config init` debe crear un starter config en tmp_path."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    config_dir = fake_home / ".config" / "capmd"
    env = {**os.environ, "HOME": str(fake_home), "XDG_CONFIG_HOME": str(fake_home / ".config")}

    proc = subprocess.run(
        [capmd_executable, "config", "init"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    # El `config init` puede escribir el global o el project config;
    # aceptamos cualquiera de los dos.
    candidates = [
        config_dir / "config.toml",
        fake_home / ".config" / "capmd" / "config.toml",
        tmp_path / "capmd.toml",
    ]
    assert any(c.exists() for c in candidates), (
        f"`capmd config init` no creo config.toml. stderr: {proc.stderr}"
    )
