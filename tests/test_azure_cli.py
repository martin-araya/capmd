"""Tests end-to-end del routing Azure (K4) vía CLI.

Usa un shim ``markitdown`` (script bash) inyectado en ``PATH`` para
mockear el comportamiento del CLI sin depender de Azure real ni de
los extras ``azure-ai-*``.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _normal_pdf(tmp_path: Path) -> Path:
    return build.build_headings_pdf(tmp_path / "Rust Handbook.pdf")


def _runner_convert(args: list[str], *, env: dict[str, str] | None = None) -> object:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return CliRunner().invoke(app, ["convert", *args], env=full_env)


def _make_markitdown_shim(
    tmp_path: Path,
    *,
    output_content: str = "# Azure mock output\n\nBody.\n",
    exit_code: int = 0,
    stderr: str = "",
    name: str = "markitdown",
) -> Path:
    """Crea un script bash que simula ``markitdown`` CLI.

    Escribe ``output_content`` al archivo pasado por ``-o`` y sale con
    ``exit_code``. Loggea el argv a un archivo para que los tests
    puedan inspeccionar qué flags recibió.
    """
    shim_dir = tmp_path / "shim_dir"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / name
    payload = shim_dir / "payload.txt"
    payload.write_text(output_content, encoding="utf-8")
    argv_log = shim_dir / "argv.log"

    shim.write_text(
        dedent(
            f"""\
            #!/bin/sh
            echo "$0 $@" >> "{argv_log}"
            OUTPUT=""
            while [ $# -gt 0 ]; do
              case "$1" in
                -o) OUTPUT="$2"; shift 2 ;;
                *) shift ;;
              esac
            done
            echo '{stderr}' >&2
            cat "{payload}" > "$OUTPUT"
            exit {exit_code}
            """
        ),
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim_dir


def _shim_path_env(tmp_path: Path) -> dict[str, str]:
    """Env con PATH apuntando al dir del shim (home también aislado)."""
    shim_dir = tmp_path / "shim_dir"
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
        "CAPMD_MARKITDOWN_BIN": str(shim_dir / "markitdown"),
    }


# ---------------------------------------------------------------------------
# help / flags
# ---------------------------------------------------------------------------


def test_cli_help_lists_azure_flags() -> None:
    """``capmd convert --help`` lista los 7 flags K4."""
    result = _runner_convert(["--help"])
    assert result.exit_code == 0
    # Typer trunca nombres largos en el help; aceptamos el prefijo o
    # el nombre truncado con "…".
    for flag in (
        "--use-cu",
        "--use-conten",  # truncated "--use-content-understanding"
        "--use-docintel",
        "--endpoint",
        "--cu-endpoint",
        "--cu-analyzer",
        "--cu-file-types",
    ):
        assert flag in result.stdout, f"--help no menciona {flag}"


def test_cli_docintel_and_use_cu_are_mutually_exclusive(tmp_path: Path) -> None:
    """``-d`` y ``--use-cu`` juntos → exit 2 con mensaje claro."""
    pdf = _normal_pdf(tmp_path)
    result = _runner_convert(
        [str(pdf), "-d", "--use-cu", "-e", "https://x", "--cu-endpoint", "https://y", "-o", str(tmp_path / "out.md")],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code != 0
    assert "mutuamente excluyentes" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Routing activo: subprocess se invoca con los flags correctos
# ---------------------------------------------------------------------------


def test_cli_use_cu_invokes_markitdown_with_cu_flags(tmp_path: Path) -> None:
    """``--use-cu --cu-endpoint X --cu-analyzer Y --cu-file-types Z`` → argv correcto."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out.md"
    shim_dir = _make_markitdown_shim(tmp_path)

    result = _runner_convert(
        [
            str(pdf),
            "--use-cu",
            "--cu-endpoint", "https://cu.example",
            "--cu-analyzer", "prebuilt-documentAnalyzer",
            "--cu-file-types", "pdf,jpeg",
            "-o", str(out),
        ],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert out.is_file()
    argv_log = shim_dir / "argv.log"
    argv_text = argv_log.read_text(encoding="utf-8")
    assert "--use-cu" in argv_text
    assert "https://cu.example" in argv_text
    assert "prebuilt-documentAnalyzer" in argv_text
    assert "pdf,jpeg" in argv_text


def test_cli_use_docintel_invokes_markitdown_with_docintel_flags(
    tmp_path: Path,
) -> None:
    """``-d -e URL`` → argv con ``-d`` y ``-e URL``."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out.md"
    shim_dir = _make_markitdown_shim(tmp_path)

    result = _runner_convert(
        [
            str(pdf),
            "-d",
            "-e", "https://di.example",
            "-o", str(out),
        ],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    argv_text = (shim_dir / "argv.log").read_text(encoding="utf-8")
    assert " -d " in argv_text or argv_text.endswith(" -d")
    assert "https://di.example" in argv_text


def test_cli_env_endpoint_only_uses_normal_path(tmp_path: Path) -> None:
    """Env var sin flag CLI → NO spawnea markitdown (routing inactivo).

    Decisión K4: env vars no auto-activan el routing (evitar llamadas
    accidentales a la API).
    """
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out.md"
    _make_markitdown_shim(tmp_path)

    _runner_convert(
        [str(pdf), "-o", str(out)],
        env={
            **_shim_path_env(tmp_path),
            "MARKITDOWN_CU_ENDPOINT": "https://cu",
        },
    )
    # El extractor built-in de markitdown corre; el shim NO se invoca
    # (routing inactivo porque no hay flag CLI). Verificamos que out.md
    # viene del flujo normal (FM de capmd, no del shim).
    assert out.is_file()
    fm = out.read_text(encoding="utf-8")
    assert "capmd_version" in fm  # FM de capmd (no shimmer)


def test_cli_env_endpoint_with_flag_uses_env_endpoint(
    tmp_path: Path,
) -> None:
    """Env var + ``--use-cu`` (sin ``--cu-endpoint``) → usa endpoint del env."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out.md"
    shim_dir = _make_markitdown_shim(tmp_path)

    result = _runner_convert(
        [str(pdf), "--use-cu", "-o", str(out)],
        env={
            **_shim_path_env(tmp_path),
            "MARKITDOWN_CU_ENDPOINT": "https://from-env.example",
        },
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    argv_text = (shim_dir / "argv.log").read_text(encoding="utf-8")
    assert "--use-cu" in argv_text
    assert "https://from-env.example" in argv_text


# ---------------------------------------------------------------------------
# Pipeline integration: el resto del pipeline corre sobre el output Azure
# ---------------------------------------------------------------------------


def test_cli_pipeline_runs_cleaners_after_azure(tmp_path: Path) -> None:
    """Cleaners corren sobre el output del shim markitdown (K4 respeta pipeline)."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out.md"
    # Shim devuelve markdown con guiones cortados y blanks extra.
    _make_markitdown_shim(
        tmp_path,
        output_content=(
            "pala-\n"
            "bra rota\n"
            "\n"
            "\n\n\n"
            "otra\n"
            "sección\n"
        ),
    )

    result = _runner_convert(
        [str(pdf), "--use-cu", "--cu-endpoint", "https://x", "-o", str(out)],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    body = out.read_text(encoding="utf-8")
    # ParagraphJoins debería unir "pala-\nbra" → "palabra".
    assert "palabra rota" in body
    # Whitespace debería colapsar 3+ newlines a 2.
    assert "\n\n\n\n" not in body


def test_cli_post_command_hook_fires_after_azure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K3 hook fires con el path al output Azure."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out.md"
    log = tmp_path / "log.txt"
    hook = tmp_path / "hook.sh"
    hook.write_text(f'#!/bin/sh\necho "$1" > "{log}"\n')
    hook.chmod(0o755)
    cfg = tmp_path / "capmd.toml"
    cfg.write_text(f'[hooks]\npost_command = "{hook}"\n')

    # Redirigir el binario ``markitdown`` al shim del tmpdir via
    # ``CAPMD_MARKITDOWN_BIN`` (env var que el runner consulta desde
    # ``os.environ``).
    _make_markitdown_shim(tmp_path)
    shim_dir = tmp_path / "shim_dir"
    monkeypatch.setenv("CAPMD_MARKITDOWN_BIN", str(shim_dir / "markitdown"))

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = _runner_convert(
            [str(pdf), "--use-cu", "--cu-endpoint", "https://x", "-o", str(out)],
            env=_shim_path_env(tmp_path),
        )
    finally:
        os.chdir(old_cwd)

    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert log.is_file(), "hook no se invocó sobre output Azure"
    assert log.read_text(encoding="utf-8").strip() == str(out.resolve())


def test_cli_images_still_extracted_after_azure(tmp_path: Path) -> None:
    """La extracción de imágenes corre DESPUÉS de Azure (independiente)."""
    # build_two_images_pdf inserta 2 imágenes reales en el PDF.
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    pdf = build.build_two_images_pdf(tmp_path / "book.pdf", work_dir=work)
    out_dir = tmp_path / "out"
    _make_markitdown_shim(
        tmp_path,
        output_content="# Image chapter\n\nBody.\n![img](images/x.png)\n",
    )

    result = _runner_convert(
        [
            str(pdf),
            "--use-cu",
            "--cu-endpoint", "https://x",
            "--out", str(out_dir),
        ],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    # El book slug deriva del filename ("book" → "book"). El árbol
    # se crea con la pipeline de imágenes corriendo sobre el output
    # del shim.
    assert (out_dir / "book").exists()


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


def test_cli_azure_failure_propagates_as_capmd_error(
    tmp_path: Path,
) -> None:
    """Shim que sale con exit != 0 → capmd exit 5 (AzureConversionFailed)."""
    pdf = _normal_pdf(tmp_path)
    _make_markitdown_shim(
        tmp_path,
        exit_code=7,
        stderr="ImportError: azure-ai-contentunderstanding not installed",
    )

    result = _runner_convert(
        [str(pdf), "--use-cu", "--cu-endpoint", "https://x", "-o", str(tmp_path / "out.md")],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code == 5
    assert "azure" in result.stderr.lower() or "azure-ai" in result.stderr.lower()


def test_cli_azure_missing_binary_gives_actionable_hint(
    tmp_path: Path,
) -> None:
    """Sin ``markitdown`` en PATH → exit 3 con hint ``pip install markitdown[...]``."""
    pdf = _normal_pdf(tmp_path)
    # PATH vacío de shims: solo el real del sistema (sin markitdown en este test).
    home = tmp_path / "home"
    home.mkdir()
    result = _runner_convert(
        [str(pdf), "--use-cu", "--cu-endpoint", "https://x", "-o", str(tmp_path / "out.md")],
        env={
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            # PATH minimal: solo /usr/bin (markitdown no está acá usualmente).
            "PATH": "/usr/bin:/bin",
        },
    )
    if result.exit_code == 0:
        pytest.skip("markitdown real está instalado en este sistema; skip")
    assert result.exit_code == 3
    assert "markitdown" in result.stderr.lower()
    assert "pip install" in result.stderr.lower()


def test_cli_timeout_propagates_to_azure_subprocess(tmp_path: Path) -> None:
    """``--timeout 0.1`` con shim que duerme → exit 5 con hint timeout."""
    pdf = _normal_pdf(tmp_path)
    out = tmp_path / "out.md"

    shim_dir = tmp_path / "shim_dir"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "markitdown"
    payload = shim_dir / "payload.txt"
    payload.write_text("# body\n")
    shim.write_text(
        "#!/bin/sh\n"
        "OUTPUT=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in -o) OUTPUT=\"$2\"; shift 2 ;; *) shift ;; esac\n"
        "done\n"
        "sleep 5\n"
        "cat \"payload.txt\" > \"$OUTPUT\"\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)

    result = _runner_convert(
        [str(pdf), "--use-cu", "--cu-endpoint", "https://x", "--timeout", "1", "-o", str(out)],
        env=_shim_path_env(tmp_path),
    )
    assert result.exit_code == 5
    assert "timeout" in result.stderr.lower()
