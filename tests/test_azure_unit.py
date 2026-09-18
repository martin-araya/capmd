"""Tests unitarios de ``capmd.convert.azure`` (K4).

Cubre el resolver, el argv builder y el subprocess runner (con shim).
"""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

import pytest

from capmd.convert.azure import (
    AZURE_STDERR_TAIL_LINES,
    AZURE_TIMEOUT_DEFAULT,
    AzureRouting,
    build_markitdown_argv,
    resolve_azure_routing,
    run_markitdown_subprocess,
)
from capmd.errors import AzureBackendMissing, AzureConversionFailed

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_markitdown_shim(
    tmp_path: Path,
    *,
    output_content: str = "# mock azure output\n\nbody.\n",
    exit_code: int = 0,
    stderr: str = "",
    sleep_secs: float = 0.0,
    name: str = "markitdown",
) -> Path:
    """Crea un script bash que simula ``markitdown`` CLI.

    Escribe ``output_content`` al archivo pasado por ``-o`` y sale con
    ``exit_code``. Si ``sleep_secs > 0``, duerme antes de salir (útil
    para tests de timeout).

    El contenido se escribe via ``cat <<EOF`` para preservar newlines
    literalmente (sin escape issues).
    """
    shim = tmp_path / name
    payload_file = tmp_path / "shim_payload.txt"
    payload_file.write_text(output_content, encoding="utf-8")
    shim.write_text(
        "#!/bin/sh\n"
        f"sleep {sleep_secs}\n"
        f"echo '{stderr}' >&2\n"
        f"OUTPUT=\"\"\n"
        f"while [ $# -gt 0 ]; do\n"
        f"  case \"$1\" in\n"
        f"    -o) OUTPUT=\"$2\"; shift 2 ;;\n"
        f"    *) shift ;;\n"
        f"  esac\n"
        f"done\n"
        f"cat \"{payload_file}\" > \"$OUTPUT\"\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


# ---------------------------------------------------------------------------
# AzureRouting dataclass
# ---------------------------------------------------------------------------


def test_azure_routing_defaults_all_inactive() -> None:
    """Defaults: ningún backend activo, endpoints None."""
    r = AzureRouting()
    assert r.is_active is False
    assert r.use_cu is False
    assert r.use_docintel is False
    assert r.docintel_endpoint is None
    assert r.cu_endpoint is None
    assert r.cu_analyzer is None
    assert r.cu_file_types is None
    assert r.timeout_seconds == AZURE_TIMEOUT_DEFAULT


def test_azure_routing_is_active_for_cu() -> None:
    """is_active es True cuando ``use_cu``."""
    r = AzureRouting(use_cu=True, cu_endpoint="https://x")
    assert r.is_active is True


def test_azure_routing_is_active_for_docintel() -> None:
    """is_active es True cuando ``use_docintel``."""
    r = AzureRouting(use_docintel=True, docintel_endpoint="https://x")
    assert r.is_active is True


# ---------------------------------------------------------------------------
# resolve_azure_routing — precedence
# ---------------------------------------------------------------------------


def test_resolve_no_flags_no_env_returns_disabled() -> None:
    """Sin flags CLI ni env vars → routing inactivo."""
    r = resolve_azure_routing(env={})
    assert r.is_active is False


def test_resolve_cli_use_cu_only() -> None:
    """``cli_use_cu=True`` → CU activo."""
    r = resolve_azure_routing(cli_use_cu=True, env={})
    assert r.use_cu is True
    assert r.use_docintel is False
    assert r.cu_endpoint is None


def test_resolve_cli_docintel_with_endpoint() -> None:
    """``cli_use_docintel=True`` + endpoint CLI → DocIntel con endpoint."""
    r = resolve_azure_routing(
        cli_use_docintel=True,
        cli_docintel_endpoint="https://di.example",
        env={},
    )
    assert r.use_docintel is True
    assert r.docintel_endpoint == "https://di.example"


def test_resolve_env_endpoint_only_no_routing_activated() -> None:
    """Env var set sin flag CLI → endpoint guardado pero routing inactivo.

    Decisión K4: el routing solo se activa con flag CLI explícito, para
    evitar llamadas a la API accidentales.
    """
    r = resolve_azure_routing(
        env={"MARKITDOWN_CU_ENDPOINT": "https://env-cu"},
    )
    assert r.is_active is False
    assert r.cu_endpoint == "https://env-cu"  # guardado para cuando se active


def test_resolve_cli_overrides_env() -> None:
    """CLI flag > env var en el campo correspondiente."""
    r = resolve_azure_routing(
        cli_use_cu=True,
        cli_cu_endpoint="https://cli-endpoint",
        env={"MARKITDOWN_CU_ENDPOINT": "https://env-endpoint"},
    )
    assert r.cu_endpoint == "https://cli-endpoint"


def test_resolve_both_env_keeps_routing_inactive() -> None:
    """Ambas env vars sin flag CLI → routing INACTIVO (decisión K4).

    Los endpoints se guardan igual (para cuando el usuario agregue el
    flag CLI), pero ``is_active=False`` evita llamadas accidentales.
    """
    r = resolve_azure_routing(
        env={
            "MARKITDOWN_DOCINTEL_ENDPOINT": "https://di",
            "MARKITDOWN_CU_ENDPOINT": "https://cu",
        },
    )
    assert r.is_active is False
    assert r.docintel_endpoint == "https://di"
    assert r.cu_endpoint == "https://cu"


def test_resolve_cli_use_cu_silently_overrides_docintel_env() -> None:
    """CLI ``--use-cu`` + env var DocIntel → CLI gana, sin warning.

    El endpoint DocIntel se guarda igual (la CLI lo necesitaría si el
    usuario cambia a ``-d`` después), pero ``use_docintel`` queda False.
    """
    r = resolve_azure_routing(
        cli_use_cu=True,
        env={"MARKITDOWN_DOCINTEL_ENDPOINT": "https://di"},
    )
    assert r.use_cu is True
    assert r.use_docintel is False
    assert r.docintel_endpoint == "https://di"  # guardado para referencia


# ---------------------------------------------------------------------------
# build_markitdown_argv
# ---------------------------------------------------------------------------


def test_build_argv_docintel_with_endpoint() -> None:
    """DocIntel con endpoint: argv incluye ``-d`` y ``-e <url>``."""
    r = AzureRouting(
        use_docintel=True,
        docintel_endpoint="https://di.example",
    )
    argv = build_markitdown_argv("input.pdf", "out.md", r)
    assert "-d" in argv
    assert "-e" in argv
    assert "https://di.example" in argv
    assert "input.pdf" in argv
    assert "-o" in argv
    assert "out.md" in argv


def test_build_argv_cu_with_analyzer_and_file_types() -> None:
    """CU con analyzer + file_types: argv incluye los 3 flags."""
    r = AzureRouting(
        use_cu=True,
        cu_endpoint="https://cu.example",
        cu_analyzer="prebuilt-documentAnalyzer",
        cu_file_types="pdf,jpeg,mp4",
    )
    argv = build_markitdown_argv("input.pdf", "out.md", r)
    assert "--use-cu" in argv
    assert "--cu-endpoint" in argv
    assert "https://cu.example" in argv
    assert "--cu-analyzer" in argv
    assert "prebuilt-documentAnalyzer" in argv
    assert "--cu-file-types" in argv
    assert "pdf,jpeg,mp4" in argv


def test_build_argv_docintel_without_endpoint_omits_e() -> None:
    """DocIntel sin endpoint: ``-d`` sí, ``-e`` no (markitdown falla con su propio error)."""
    r = AzureRouting(use_docintel=True)
    argv = build_markitdown_argv("input.pdf", "out.md", r)
    assert "-d" in argv
    assert "-e" not in argv


def test_build_argv_disabled_raises_value_error() -> None:
    """``routing.is_active=False`` → el caller no debería invocar esto."""
    r = AzureRouting()
    with pytest.raises(ValueError) as exc_info:
        build_markitdown_argv("input.pdf", "out.md", r)
    assert "is_active" in str(exc_info.value)


def test_build_argv_cu_without_optional_flags() -> None:
    """CU sin analyzer/file_types: argv incluye solo ``--use-cu`` (sin endpoint si vacío)."""
    r = AzureRouting(use_cu=True)
    argv = build_markitdown_argv("input.pdf", "out.md", r)
    assert "--use-cu" in argv
    assert "--cu-endpoint" not in argv
    assert "--cu-analyzer" not in argv
    assert "--cu-file-types" not in argv


# ---------------------------------------------------------------------------
# run_markitdown_subprocess
# ---------------------------------------------------------------------------


def test_run_markitdown_returns_markdown_when_mocked(tmp_path: Path) -> None:
    """Shim markitdown escribe markdown fijo → lo devolvemos."""
    shim = _make_markitdown_shim(
        tmp_path,
        output_content="# Azure output\n\nbody.\n",
    )
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\nfake pdf content\n")
    output_md = tmp_path / "out.md"

    r = AzureRouting(use_cu=True, cu_endpoint="https://x")
    argv_str = run_markitdown_subprocess(
        input_path=str(input_pdf),
        output_path=str(output_md),
        routing=r,
        markitdown_bin=str(shim),
    )
    assert "markitdown" in argv_str
    assert output_md.is_file()
    assert output_md.read_text(encoding="utf-8") == "# Azure output\n\nbody.\n"


def test_run_markitdown_raises_when_binary_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATH sin markitdown → ``AzureBackendMissing``."""
    # Asegurar que shutil.which retorne None incluso si el sistema lo tiene.
    monkeypatch.setattr(shutil, "which", lambda _: None)

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    r = AzureRouting(use_cu=True)

    with pytest.raises(AzureBackendMissing) as exc_info:
        run_markitdown_subprocess(
            input_path=str(input_pdf),
            output_path=str(tmp_path / "out.md"),
            routing=r,
        )
    assert exc_info.value.exit_code == 3
    assert "markitdown[docintel,cu]" in (exc_info.value.hint or "")


def test_run_markitdown_propagates_failure(tmp_path: Path) -> None:
    """Shim que retorna exit 7 + stderr → ``AzureConversionFailed`` con hint."""
    shim = _make_markitdown_shim(
        tmp_path,
        exit_code=7,
        stderr="ImportError: azure-ai-documentintelligence not installed",
    )
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    r = AzureRouting(use_docintel=True, docintel_endpoint="https://x")

    with pytest.raises(AzureConversionFailed) as exc_info:
        run_markitdown_subprocess(
            input_path=str(input_pdf),
            output_path=str(tmp_path / "out.md"),
            routing=r,
            markitdown_bin=str(shim),
        )
    assert exc_info.value.exit_code == 5
    hint = exc_info.value.hint or ""
    assert "azure-ai-documentintelligence" in hint


def test_run_markitdown_timeout_returns_timed_out(tmp_path: Path) -> None:
    """Shim que duerme > timeout → ``AzureConversionFailed`` con hint timeout."""
    shim = _make_markitdown_shim(tmp_path, sleep_secs=5.0)
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    r = AzureRouting(use_cu=True, timeout_seconds=0.3)

    with pytest.raises(AzureConversionFailed) as exc_info:
        run_markitdown_subprocess(
            input_path=str(input_pdf),
            output_path=str(tmp_path / "out.md"),
            routing=r,
            markitdown_bin=str(shim),
        )
    assert "timeout" in (exc_info.value.hint or "").lower()


def test_run_markitdown_filters_capmd_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las env vars ``CAPMD_*`` NO se pasan al subprocess (child no las entiende)."""
    shim_path = tmp_path / "markitdown"
    env_dump_path = tmp_path / "captured_env.txt"

    # Shim que dumpea el env y matchea el patrón -o FILE.
    shim_body = (
        "#!/bin/sh\n"
        f"env > {env_dump_path}\n"
        "OUTPUT=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -o) OUTPUT=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "echo '# ok' > \"$OUTPUT\"\n"
    )
    shim_path.write_text(shim_body, encoding="utf-8")
    shim_path.chmod(0o755)

    monkeypatch.setenv("CAPMD_TEST_VAR", "should_not_leak")

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")

    r = AzureRouting(use_cu=True)
    output_md = tmp_path / "out.md"
    run_markitdown_subprocess(
        input_path=str(input_pdf),
        output_path=str(output_md),
        routing=r,
        markitdown_bin=str(shim_path),
    )

    if env_dump_path.exists():
        captured = env_dump_path.read_text(encoding="utf-8")
        assert "CAPMD_TEST_VAR" not in captured


def test_run_markitdown_disabled_raises_value_error(tmp_path: Path) -> None:
    """``routing.is_active=False`` → ``ValueError``."""
    shim = _make_markitdown_shim(tmp_path)
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(ValueError):
        run_markitdown_subprocess(
            input_path=str(input_pdf),
            output_path=str(tmp_path / "out.md"),
            routing=AzureRouting(),
            markitdown_bin=str(shim),
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_azure_constants_have_expected_values() -> None:
    """Los defaults del módulo son los documentados."""
    assert AZURE_TIMEOUT_DEFAULT == 600.0
    assert AZURE_STDERR_TAIL_LINES == 20
