"""Routing a Azure Document Intelligence / Content Understanding (K4).

capmd expone los flags de ``markitdown`` para enrutamiento a backends
cloud de Azure (``-d/--use-docintel``, ``--use-cu``, ``-e/--endpoint``,
``--cu-endpoint``, ``--cu-analyzer``, ``--cu-file-types``) y lee las
env vars ``MARKITDOWN_DOCINTEL_ENDPOINT`` / ``MARKITDOWN_CU_ENDPOINT``.

Como el API Python de ``markitdown.MarkItDown`` no expone esos flags
como constructor params, la integración se hace via **subprocess** al
CLI ``markitdown``: capmd spawnea ``markitdown`` con los flags
apropiados, captura el markdown resultante a un tmpfile, y lo pasa
por el resto del pipeline (cleaners, FM, images, hooks, study,
split). El Azure solo reemplaza el step de extracción inicial; el
resto del pipeline no cambia.

Endpoints via CLI flag ganan sobre env vars; CU gana sobre DocIntel
si ambos están activos sin flag CLI explícita (warning a stderr).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

from capmd.errors import AzureBackendMissing, AzureConversionFailed

__all__ = [
    "AZURE_STDERR_TAIL_LINES",
    "AZURE_TIMEOUT_DEFAULT",
    "AzureRouting",
    "build_markitdown_argv",
    "resolve_azure_routing",
    "run_markitdown_subprocess",
]


AZURE_TIMEOUT_DEFAULT: float = 600.0
"""Timeout default para el subprocess de ``markitdown`` (segundos)."""

AZURE_STDERR_TAIL_LINES: int = 20
"""Cantidad máxima de líneas del stderr de markitdown que se reportan
cuando hay un fallo (para no explotar los logs)."""

_AZURE_HINT = (
    "instalá markitdown con los extras de Azure: "
    "`pip install 'markitdown[docintel,cu]'` "
    "(o `pip install 'markitdown[all]'` para todos los extras)"
)


@dataclass(frozen=True)
class AzureRouting:
    """Resultado de resolver flags CLI + env vars para backends Azure.

    ``use_cu`` y ``use_docintel`` son mutuamente excluyentes (resolución
    los hace colapsar a uno solo). Los campos ``*_endpoint`` y
    ``cu_*`` adicionales son opcionales.
    """

    use_cu: bool = False
    use_docintel: bool = False
    docintel_endpoint: str | None = None
    cu_endpoint: str | None = None
    cu_analyzer: str | None = None
    cu_file_types: str | None = None
    timeout_seconds: float = AZURE_TIMEOUT_DEFAULT

    @property
    def is_active(self) -> bool:
        """``True`` si hay un backend Azure seleccionado (no ``unrouted``)."""
        return self.use_cu or self.use_docintel


def resolve_azure_routing(
    *,
    cli_use_cu: bool = False,
    cli_use_docintel: bool = False,
    cli_docintel_endpoint: str | None = None,
    cli_cu_endpoint: str | None = None,
    cli_cu_analyzer: str | None = None,
    cli_cu_file_types: str | None = None,
    timeout_seconds: float = AZURE_TIMEOUT_DEFAULT,
    env: Mapping[str, str] | None = None,
) -> AzureRouting:
    """Resuelve flags CLI + env vars con precedencia y warning.

    Precedencia:
      - Flag CLI > env var (en el campo correspondiente).
      - Si ``cli_use_cu`` está set, CU gana (incluso si env var
        DocIntel está presente) — es decisión explícita del usuario.
      - Si ambas env vars DocIntel + CU están seteadas sin flag CLI,
        gana CU y se emite un warning vía logger (decisión documentada
        en el plan K4).

    Args:
        cli_use_cu: ``--use-cu`` desde CLI.
        cli_use_docintel: ``-d/--use-docintel`` desde CLI.
        cli_docintel_endpoint: ``-e/--endpoint`` desde CLI.
        cli_cu_endpoint: ``--cu-endpoint`` desde CLI.
        cli_cu_analyzer: ``--cu-analyzer`` desde CLI.
        cli_cu_file_types: ``--cu-file-types`` desde CLI (comma-separated).
        timeout_seconds: ``--timeout`` desde CLI.
        env: mapping de env vars (``os.environ`` por default).

    Returns:
        :class:`AzureRouting` con todos los campos resueltos.
    """
    if env is None:
        env = os.environ

    env_di = env.get("MARKITDOWN_DOCINTEL_ENDPOINT") or None
    env_cu = env.get("MARKITDOWN_CU_ENDPOINT") or None

    # Decidir qué backend gana. **Solo los flags CLI activan el
    # routing** (decisión K4: las env vars NO auto-activan, para
    # evitar llamadas a la API accidentales).
    use_cu: bool
    use_docintel: bool
    warning_msg: str | None = None

    if cli_use_cu and cli_use_docintel:
        # Mutuamente excluyentes a nivel CLI; la validación debe
        # ocurrir antes (typer.BadParameter). Si llega acá, le damos
        # prioridad a CU (último gana) por consistencia.
        use_cu = True
        use_docintel = False
        warning_msg = (
            "ambos -d y --use-cu pasados por CLI; usando CU (CU gana)"
        )
    elif cli_use_cu:
        use_cu = True
        use_docintel = False
    elif cli_use_docintel:
        use_docintel = True
        use_cu = False
    else:
        # Sin flag CLI: el routing queda inactivo aunque haya env vars.
        use_cu = False
        use_docintel = False

    # Resolver endpoints: CLI > env. Si el routing está inactivo,
    # igualmente guardamos los endpoints para que ``is_active=False``
    # pero la CLI pueda pasarlos a markitdown si el usuario decide
    # agregar el flag CLI después (workflow interactivo). Decisión K4.
    docintel_endpoint = cli_docintel_endpoint or env_di
    cu_endpoint = cli_cu_endpoint or env_cu

    # Log warning si hubo.
    if warning_msg is not None:
        import logging

        logging.getLogger(__name__).warning(warning_msg)

    return AzureRouting(
        use_cu=use_cu,
        use_docintel=use_docintel,
        docintel_endpoint=docintel_endpoint,
        cu_endpoint=cu_endpoint,
        cu_analyzer=cli_cu_analyzer,
        cu_file_types=cli_cu_file_types,
        timeout_seconds=timeout_seconds,
    )


def build_markitdown_argv(
    input_path: str,
    output_path: str,
    routing: AzureRouting,
) -> list[str]:
    """Construye el argv para invocar ``markitdown`` CLI.

    Raises:
        ValueError: si ``routing`` no tiene ningún backend activo
            (el caller debería chequear ``routing.is_active`` antes).
    """
    if not routing.is_active:
        raise ValueError(
            "build_markitdown_argv requiere routing.is_active=True "
            "(ningún backend Azure seleccionado)"
        )

    argv: list[str] = ["markitdown", input_path, "-o", output_path]

    if routing.use_docintel:
        argv.append("-d")
        if routing.docintel_endpoint:
            argv.extend(["-e", routing.docintel_endpoint])
    elif routing.use_cu:
        argv.append("--use-cu")
        if routing.cu_endpoint:
            argv.extend(["--cu-endpoint", routing.cu_endpoint])
        if routing.cu_analyzer:
            argv.extend(["--cu-analyzer", routing.cu_analyzer])
        if routing.cu_file_types:
            argv.extend(["--cu-file-types", routing.cu_file_types])

    return argv


def _truncate(text: str, max_lines: int = AZURE_STDERR_TAIL_LINES) -> str:
    """Devuelve las últimas ``max_lines`` líneas del texto."""
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[-max_lines:])


def run_markitdown_subprocess(
    input_path: str,
    output_path: str,
    routing: AzureRouting,
    *,
    markitdown_bin: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> str:
    """Ejecuta ``markitdown`` CLI con routing Azure y devuelve el argv completo.

    Espera a que termine (síncrono) y levanta :class:`AzureBackendMissing`
    si el binario no existe o :class:`AzureConversionFailed` si el
    subprocess falla.

    Args:
        input_path: archivo de entrada (PDF, JPEG, etc.).
        output_path: archivo donde ``markitdown`` CLI escribe el markdown.
        routing: routing resuelto (de :func:`resolve_azure_routing`).
        markitdown_bin: override del binario a invocar (default
            ``shutil.which("markitdown")``). Útil para tests que inyectan
            un shim.
        extra_env: env vars adicionales a pasar al subprocess (se
            mergean con las env vars del proceso actual, filtrando las
            ``CAPMD_*`` para no contaminar al child).

    Returns:
        El argv que se ejecutó (útil para tests y para logging).

    Raises:
        AzureBackendMissing: si el binario ``markitdown`` no está en PATH.
        AzureConversionFailed: si el subprocess devuelve exit != 0 o
            supera el timeout.
    """
    if not routing.is_active:
        raise ValueError(
            "run_markitdown_subprocess requiere routing.is_active=True"
        )

    bin_path = markitdown_bin
    if bin_path is None and "CAPMD_MARKITDOWN_BIN" in os.environ:
        bin_path = os.environ["CAPMD_MARKITDOWN_BIN"]
    if bin_path is None:
        # Si ``extra_env`` provee PATH (típicamente en tests con shim),
        # respetarlo; si no, usar el PATH del proceso.
        search_path = (
            extra_env.get("PATH") if extra_env else None
        ) or os.environ.get("PATH")
        bin_path = shutil.which("markitdown", path=search_path)
    if bin_path is None:
        raise AzureBackendMissing(
            "no se encontró el binario 'markitdown' en PATH",
            hint=_AZURE_HINT,
        )

    argv = build_markitdown_argv(input_path, output_path, routing)
    argv[0] = bin_path  # usar el binario resuelto

    # Construir env limpia: inherit del OS pero filtrar CAPMD_* (excepto
    # CAPMD_MARKITDOWN_BIN) para no contaminar al child (markitdown no
    # las entiende, pero CAPMD_MARKITDOWN_BIN es un override nuestro
    # para tests/CI).
    child_env: dict[str, str] = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CAPMD_") or k == "CAPMD_MARKITDOWN_BIN"
    }
    if extra_env:
        child_env.update(dict(extra_env))

    timeout = (
        routing.timeout_seconds
        if routing.timeout_seconds is not None
        else AZURE_TIMEOUT_DEFAULT
    )

    try:
        proc = subprocess.run(
            argv,
            shell=False,
            env=child_env,
            timeout=None if timeout < 0 else timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stderr_text = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        raise AzureConversionFailed(
            f"markitdown (Azure) timeout después de {timeout}s",
            hint=_truncate(
                stderr_text
                + f"\ntimeout after {timeout}s; "
                "subí --timeout o revisá el endpoint"
            ),
        ) from exc
    except FileNotFoundError as exc:
        raise AzureBackendMissing(
            f"binario markitdown no encontrado en {bin_path}",
            hint=_AZURE_HINT,
        ) from exc
    except OSError as exc:
        raise AzureConversionFailed(
            f"error OS al correr markitdown (Azure): {exc}",
            hint=_truncate(str(exc)),
        ) from exc

    if proc.returncode != 0:
        raise AzureConversionFailed(
            f"markitdown (Azure) salió con exit code {proc.returncode}",
            hint=_truncate(proc.stderr or "")
            + "\nverificá endpoint, extras Azure instalados, o "
            "permisos del archivo de entrada",
        )

    return " ".join(argv)
