"""Tests end-to-end de ``capmd compare`` (K5) vía CLI.

Usa el shim ``markitdown`` (script bash) inyectado via
``CAPMD_MARKITDOWN_BIN`` para mockear el motor CU/DocIntel sin
depender de Azure real (mismo patrón que K4).
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _outline_pdf(tmp_path: Path, n_pages: int = 20) -> Path:
    return build.build_many_pages_pdf(tmp_path / "Rust Handbook.pdf", n_pages=n_pages)


def _make_markitdown_shim(
    tmp_path: Path,
    *,
    output_content: str = "# Azure K5 mock\n\nBody from mock Azure CU.\n",
    exit_code: int = 0,
    name: str = "markitdown",
) -> Path:
    """Crea un script bash que simula ``markitdown`` CLI.

    Parsea el flag ``-o OUTPUT`` del argv (markitdown style).
    """
    shim_dir = tmp_path / "shim_dir"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / name
    payload = shim_dir / "payload.txt"
    payload.write_text(output_content, encoding="utf-8")

    shim.write_text(
        dedent(
            f"""\
            #!/bin/sh
            OUTPUT=""
            while [ $# -gt 0 ]; do
              case "$1" in
                -o) OUTPUT="$2"; shift 2 ;;
                *) shift ;;
              esac
            done
            cat "{payload}" > "$OUTPUT"
            exit {exit_code}
            """
        ),
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim_dir


def _shim_path_env(tmp_path: Path) -> dict[str, str]:
    """Env con ``PATH`` apuntando al shim dir + ``CAPMD_MARKITDOWN_BIN``."""
    shim_dir = tmp_path / "shim_dir"
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
        "CAPMD_MARKITDOWN_BIN": str(shim_dir / "markitdown"),
    }


def _runner_compare(
    args: list[str], *, env: dict[str, str] | None = None
) -> object:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return CliRunner().invoke(app, ["compare", *args], env=full_env)


# ---------------------------------------------------------------------------
# help / registration
# ---------------------------------------------------------------------------


def test_cli_help_lists_options() -> None:
    """``capmd compare --help`` lista los flags del comparador."""
    result = _runner_compare(["--help"])
    assert result.exit_code == 0
    for flag in (
        "--pages",
        "--timeout",
        "--format",
        "--ocr-engine",
    ):
        assert flag in result.stdout, f"--help no menciona {flag}"


def test_cli_compare_help_describes_k5() -> None:
    """El help describe el comportamiento K5 (motores built-in/CU/OCR)."""
    result = _runner_compare(["--help"])
    assert result.exit_code == 0
    assert "MARKITDOWN_CU_ENDPOINT" in result.stdout
    assert "MARKITDOWN_DOCINTEL_ENDPOINT" in result.stdout
    assert "tesseract" in result.stdout or "ocrmypdf" in result.stdout


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_cli_invalid_format_exits_nonzero(tmp_path: Path) -> None:
    """``--format xml`` → exit 2 con mensaje claro."""
    pdf = _outline_pdf(tmp_path)
    result = _runner_compare(
        [str(pdf), "--format", "xml"], env=_shim_path_env(tmp_path)
    )
    assert result.exit_code != 0
    assert "format" in result.stderr.lower()


def test_cli_invalid_pages_format_exits_nonzero(tmp_path: Path) -> None:
    """``--pages "abc"`` → exit 2."""
    pdf = _outline_pdf(tmp_path)
    result = _runner_compare(
        [str(pdf), "--pages", "abc"], env=_shim_path_env(tmp_path)
    )
    assert result.exit_code != 0


def test_cli_source_not_found_exits_nonzero(tmp_path: Path) -> None:
    """PDF inexistente → exit 7 (input inválido)."""
    result = _runner_compare(
        [str(tmp_path / "no-existe.pdf")],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Happy path: table + JSON con 2+ motores
# ---------------------------------------------------------------------------


def test_cli_compare_prints_table_with_at_least_2_motors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con ``MARKITDOWN_CU_ENDPOINT`` set + shim → exit 0, tabla con 2 motores."""
    _make_markitdown_shim(tmp_path)
    shim_dir = tmp_path / "shim_dir"
    monkeypatch.setenv("CAPMD_MARKITDOWN_BIN", str(shim_dir / "markitdown"))
    monkeypatch.setenv("MARKITDOWN_CU_ENDPOINT", "https://mock-cu.example")

    pdf = _outline_pdf(tmp_path, n_pages=10)
    result = _runner_compare([str(pdf), "--pages", "3-5"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert "built-in" in result.stdout
    assert "content-understanding" in result.stdout


def test_cli_compare_json_output_is_parseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--format json`` → JSON parseable con 2+ motores."""
    _make_markitdown_shim(tmp_path)
    shim_dir = tmp_path / "shim_dir"
    monkeypatch.setenv("CAPMD_MARKITDOWN_BIN", str(shim_dir / "markitdown"))
    monkeypatch.setenv("MARKITDOWN_CU_ENDPOINT", "https://mock-cu.example")

    pdf = _outline_pdf(tmp_path, n_pages=10)
    result = _runner_compare([str(pdf), "--format", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["pages"] is None
    motor_names = [m["name"] for m in payload["motors"]]
    assert "built-in" in motor_names
    assert "content-understanding" in motor_names


def test_cli_compare_pages_slicing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--pages "3-5"`` se propaga al runner."""
    _make_markitdown_shim(tmp_path)
    shim_dir = tmp_path / "shim_dir"
    monkeypatch.setenv("CAPMD_MARKITDOWN_BIN", str(shim_dir / "markitdown"))
    # Forzar PATH sin tesseract/ocrmypdf para que no aparezcan como skipped
    # (mantiene el test enfocado en pages slicing).
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    pdf = _outline_pdf(tmp_path, n_pages=20)
    result = _runner_compare([str(pdf), "--pages", "3-5", "--format", "json"])
    # Exit 8 esperado por OCR skipped. Verificamos el flag pages en el JSON.
    payload = json.loads(result.stdout)
    assert payload["pages"] == "3-5"


def test_cli_compare_only_builtin_when_no_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin env vars Azure ni OCR en PATH → solo built-in aparece como ok.

    Los OCR se reportan como "skipped" (no disponible). Exit 8
    porque ≥2 motores están reportados (built-in ok + OCR skipped)
    pero solo 1 está ok.
    """
    _make_markitdown_shim(tmp_path)
    shim_dir = tmp_path / "shim_dir"
    monkeypatch.setenv("CAPMD_MARKITDOWN_BIN", str(shim_dir / "markitdown"))
    monkeypatch.delenv("MARKITDOWN_CU_ENDPOINT", raising=False)
    monkeypatch.delenv("MARKITDOWN_DOCINTEL_ENDPOINT", raising=False)
    # Forzar PATH sin tesseract/ocrmypdf para que aparezcan como skipped.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    pdf = _outline_pdf(tmp_path, n_pages=5)
    result = _runner_compare([str(pdf), "--format", "json"])
    # Exit 8: built-in ok + 2 OCR skipped = 3 motores; solo 1 ok.
    assert result.exit_code == 8, (result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    motor_names = [m["name"] for m in payload["motors"]]
    assert "built-in" in motor_names
    assert "content-understanding" not in motor_names
    assert "docintel" not in motor_names


def test_cli_compare_skips_unavailable_ocr_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin ``tesseract`` ni ``ocrmypdf`` en PATH → esos motores "skipped".

    Exit code 8 (≥2 motores disponibles pero <2 ok) es esperado: el
    compare reporta el estado honestamente para que el usuario sepa
    que el entorno no tiene los OCR engines disponibles.
    """
    _make_markitdown_shim(tmp_path)
    shim_dir = tmp_path / "shim_dir"
    monkeypatch.setenv("CAPMD_MARKITDOWN_BIN", str(shim_dir / "markitdown"))
    # Forzar PATH a algo sin tesseract/ocrmypdf.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    pdf = _outline_pdf(tmp_path, n_pages=5)
    result = _runner_compare([str(pdf), "--format", "json"])
    # Exit 8: ≥2 motores activos (built-in ok + 2 OCR skipped), pero
    # solo 1 ok. El compare reporta el estado honestamente.
    assert result.exit_code == 8, (result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    motor_names = {m["name"]: m for m in payload["motors"]}
    assert "ocr-tesseract" in motor_names
    assert motor_names["ocr-tesseract"]["status"] == "skipped"
    assert motor_names["ocr-tesseract"]["words"] == 0
    assert "ocr-ocrmypdf" in motor_names
    assert motor_names["ocr-ocrmypdf"]["status"] == "skipped"


def test_cli_compare_with_ocr_tesseract_in_path_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si ``tesseract`` está en PATH, motor corre (mockeado)."""
    _make_markitdown_shim(tmp_path)
    shim_dir = tmp_path / "shim_dir"
    monkeypatch.setenv("CAPMD_MARKITDOWN_BIN", str(shim_dir / "markitdown"))

    tesseract_shim_dir = tmp_path / "tesseract_dir"
    tesseract_shim_dir.mkdir(exist_ok=True)
    tesseract = tesseract_shim_dir / "tesseract"
    tesseract.write_text(
        "#!/bin/sh\n# Mock tesseract\n"
        "INPUT=\"$1\"\n"
        # arg 1 es el PNG; ``$2`` es ``stdout``; ignoramos ``$2``.
        "echo 'OCR output'\n",
        encoding="utf-8",
    )
    tesseract.chmod(0o755)
    # Prepend tesseract shim al PATH (sin CAPMD_MARKITDOWN_BIN override).
    new_path = f"{tesseract_shim_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)

    pdf = _outline_pdf(tmp_path, n_pages=5)
    result = _runner_compare([str(pdf), "--format", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    ocr = next(m for m in payload["motors"] if m["name"] == "ocr-tesseract")
    # El mock devuelve exit 0 con output válido; el runner debería
    # marcarlo como "ok" (palabras > 0).
    assert ocr["status"] == "ok"
    assert ocr["words"] > 0


def test_cli_compare_invalid_ocr_engine_exits_nonzero(tmp_path: Path) -> None:
    """``--ocr-engine invalid`` → exit 2."""
    pdf = _outline_pdf(tmp_path, n_pages=5)
    result = _runner_compare(
        [str(pdf), "--ocr-engine", "invalid"],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code != 0
