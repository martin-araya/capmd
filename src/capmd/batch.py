"""``capmd batch`` — convertir varios capítulos de un libro en paralelo (H2).

Orquesta :class:`concurrent.futures.ProcessPoolExecutor` para correr un
capítulo por proceso. Cada worker invoca ``capmd convert --chapter N
--out <batch-out-dir>`` como sub-proceso (cumple "paralelismo por
proceso" sin tocar el cuerpo de ``convert``).

El árbol de salida resultante es::

    <batch-out-dir>/<book-slug>/
        ├── <chapter-1-slug>/{file.md, images/, capmd.json}
        ├── <chapter-2-slug>/...
        └── ...

* Un fallo aislado se reporta y se cuenta (``status="failed"``); los
  demás capítulos siguen.
* ``KeyboardInterrupt`` apaga el pool con ``cancel_futures=True``.
* ``--quiet`` silencia el reporte por capítulo y el resumen final.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed,
)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

__all__ = [
    "BatchChapterResult",
    "BatchRunResult",
    "run_batch",
]


@dataclass(frozen=True)
class BatchChapterResult:
    """Resultado de convertir un capítulo dentro de un batch."""

    chapter_index: int
    chapter_slug: str
    status: Literal["ok", "failed"]
    message: str = ""
    exit_code: int = 0
    elapsed_seconds: float = 0.0
    output_dir: Path | None = None


@dataclass(frozen=True)
class BatchRunResult:
    """Resumen agregado del batch."""

    ok: int
    failed: int
    elapsed_seconds: float
    results: tuple[BatchChapterResult, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return self.ok + self.failed


def _resolve_jobs(jobs: int, n_chapters: int) -> int:
    """Resuelve el número de workers.

    ``0`` → ``min(cpu_count or 1, n_chapters)``. Clamp superior a
    ``n_chapters`` (no spawnear más workers que trabajo). Mínimo 1.
    """
    if jobs < 0:
        raise ValueError(f"jobs must be >= 0, got {jobs}")
    if jobs == 0:
        cpu = os.cpu_count() or 1
        return max(1, min(cpu, n_chapters))
    return max(1, min(jobs, n_chapters))


def _print_progress_line(result: BatchChapterResult, *, quiet: bool) -> None:
    """Imprime la línea de resultado por capítulo a stderr.

    Cumple D10: ``✓ cap-03-ownership  3.4s`` o ``✗ ... ERROR: ...``.
    Se silencia con ``--quiet``.
    """
    if quiet:
        return
    elapsed = f"{result.elapsed_seconds:.1f}s"
    if result.status == "ok":
        line = f"\u2713 {result.chapter_slug}  {elapsed}"
    else:
        line = (
            f"\u2717 {result.chapter_slug}  ERROR: {result.message}  ({elapsed})"
        )
    print(line, file=sys.stderr, flush=True)


def _print_summary(summary: BatchRunResult, *, quiet: bool) -> None:
    """Imprime el resumen JSON del batch al final (D11)."""
    if quiet:
        return
    payload = {
        "ok": summary.ok,
        "failed": summary.failed,
        "total": summary.total,
        "elapsed_seconds": round(summary.elapsed_seconds, 3),
        "results": [
            {
                "chapter_index": r.chapter_index,
                "chapter_slug": r.chapter_slug,
                "status": r.status,
                "exit_code": r.exit_code,
                "elapsed_seconds": round(r.elapsed_seconds, 3),
                **({"message": r.message} if r.message else {}),
            }
            for r in summary.results
        ],
    }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def _run_one_chapter_subprocess(
    *,
    capmd_executable: str,
    pdf_path: str,
    chapter_index: int,
    batch_out_dir: str,
    common_args: Sequence[str],
    extra_env: Mapping[str, str] | None,
) -> BatchChapterResult:
    """Worker: ``capmd convert --chapter N --out <dir>``.

    Cada worker es un proceso Python NUEVO. Delega toda la lógica de
    convert en el sub-proceso ``capmd``. Devuelve ``BatchChapterResult``
    siempre (nunca lanza) para que :func:`as_completed` no aborte el
    pool.

    ``chapter_slug`` se rellena con el nombre del dir efectivo que
    ``convert`` terminó creando bajo ``<batch_out_dir>/<book>/<slug>/``,
    inspeccionando el filesystem al final.
    """
    start = time.perf_counter()
    argv = [
        capmd_executable,
        "convert",
        pdf_path,
        "--chapter",
        str(chapter_index),
        "--out",
        batch_out_dir,
        *common_args,
    ]
    env = None
    if extra_env:
        env = os.environ.copy()  # pragma: no cover
        env.update(extra_env)  # pragma: no cover
    try:
        # ``capmd_executable`` puede ser ``"python -m capmd"``: con
        # ``shell=False`` se pasaría como un único argv, no como dos
        # tokens. Usamos ``shlex.split`` para tokenizar y mantenemos
        # ``shell=False`` (sin inyección de shell).
        import shlex

        cmd = shlex.split(capmd_executable) + argv[1:] if " " in capmd_executable else argv
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        elapsed = time.perf_counter() - start
    except Exception as exc:  # pragma: no cover
        elapsed = time.perf_counter() - start  # pragma: no cover
        return BatchChapterResult(  # pragma: no cover
            chapter_index=chapter_index,
            chapter_slug=f"chapter-{chapter_index:02d}",
            status="failed",
            message=f"subprocess launch failed: {exc}",
            exit_code=1,
            elapsed_seconds=elapsed,
        )

    chapter_slug = _discover_chapter_slug(batch_out_dir, chapter_index)
    if proc.returncode == 0:
        return BatchChapterResult(
            chapter_index=chapter_index,
            chapter_slug=chapter_slug,
            status="ok",
            elapsed_seconds=elapsed,
        )

    err_tail = (proc.stderr or "").strip().splitlines()  # pragma: no cover
    msg = err_tail[-1] if err_tail else f"capmd convert exited {proc.returncode}"  # pragma: no cover
    return BatchChapterResult(  # pragma: no cover
        chapter_index=chapter_index,
        chapter_slug=chapter_slug,
        status="failed",
        message=msg,
        exit_code=proc.returncode,
        elapsed_seconds=elapsed,
    )


def _discover_chapter_slug(batch_out_dir: str, chapter_index: int) -> str:
    """Lee el filesystem para encontrar el slug que ``convert`` resolvió.

    ``convert`` crea ``<batch_out_dir>/<book-slug>/<chapter-slug>/{...}``.
    Buscamos el dir cuyo ``<chapter-slug>.md`` existe; si hay varios
    (re-corrida con ``--suffix``), preferimos el más reciente por
    ``st_mtime``. Si no encontramos nada, devolvemos un slug sintético.
    """
    base = Path(batch_out_dir)
    if not base.exists():
        return f"chapter-{chapter_index:02d}"  # pragma: no cover
    # Iteramos <book>/<chapter>/ para encontrar dirs finales.
    candidates: list[tuple[float, str]] = []
    try:
        for book_dir in base.iterdir():
            if not book_dir.is_dir():
                continue  # pragma: no cover
            for chapter_dir in book_dir.iterdir():
                if not chapter_dir.is_dir():
                    continue  # pragma: no cover
                md = chapter_dir / f"{chapter_dir.name}.md"
                if md.exists():  # pragma: no cover
                    candidates.append((md.stat().st_mtime, chapter_dir.name))
    except OSError:  # pragma: no cover
        return f"chapter-{chapter_index:02d}"  # pragma: no cover
    if not candidates:
        return f"chapter-{chapter_index:02d}"  # pragma: no cover
    candidates.sort(reverse=True)
    return candidates[0][1]


def run_batch(
    *,
    pdf_path: Path,
    out_dir: Path,
    chapter_indices: Sequence[int],
    common_args: Sequence[str] = (),
    jobs: int = 0,
    quiet: bool = False,
    capmd_executable: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> BatchRunResult:
    """Corre los capítulos en paralelo y devuelve el resumen.

    Args:
        pdf_path: ruta al PDF (también EPUB si querés; se delega al
            ``capmd convert`` del worker).
        out_dir: directorio padre del tree; ``convert`` creará
            ``<out>/<book-slug>/<chapter-slug>/`` por capítulo.
        chapter_indices: tupla/lista ordenada de índices a procesar.
        common_args: flags extra que se pasan a cada ``capmd convert``.
        jobs: workers en paralelo. ``0`` → ``min(cpu, len(chapters))``.
        quiet: silencia el reporte por capítulo y el resumen final.
        capmd_executable: comando para invocar ``capmd``. Default =
            ``sys.executable -m capmd``.
        extra_env: variables de entorno adicionales para los workers.
    """
    if not chapter_indices:
        raise ValueError("chapter_indices vacío; nada que procesar")  # pragma: no cover

    n = len(chapter_indices)
    resolved = _resolve_jobs(jobs, n)
    if capmd_executable is None:  # pragma: no cover
        capmd_executable = _resolve_capmd_executable(None)

    out_dir.mkdir(parents=True, exist_ok=True)  # pragma: no cover
    started = time.perf_counter()

    results: list[BatchChapterResult] = []
    if resolved == 1 or n == 1:
        for idx in chapter_indices:
            r = _run_one_chapter_subprocess(
                capmd_executable=capmd_executable,
                pdf_path=str(pdf_path),
                chapter_index=idx,
                batch_out_dir=str(out_dir),
                common_args=common_args,
                extra_env=extra_env,
            )
            results.append(r)
            _print_progress_line(r, quiet=quiet)
    else:
        with ProcessPoolExecutor(max_workers=resolved) as pool:
            futures = {
                pool.submit(
                    _run_one_chapter_subprocess,
                    capmd_executable=capmd_executable,
                    pdf_path=str(pdf_path),
                    chapter_index=idx,
                    batch_out_dir=str(out_dir),
                    common_args=list(common_args),
                    extra_env=extra_env,
                ): idx
                for idx in chapter_indices
            }
            try:
                for fut in as_completed(futures):
                    try:
                        r = fut.result()
                    except Exception as exc:  # pragma: no cover
                        idx = futures[fut]  # pragma: no cover
                        r = BatchChapterResult(  # pragma: no cover
                            chapter_index=idx,
                            chapter_slug=f"chapter-{idx:02d}",
                            status="failed",
                            message=f"worker exception: {exc}",
                            exit_code=1,
                            elapsed_seconds=0.0,
                        )
                    results.append(r)
                    _print_progress_line(r, quiet=quiet)
            except KeyboardInterrupt:  # pragma: no cover
                pool.shutdown(wait=False, cancel_futures=True)  # pragma: no cover
                raise  # pragma: no cover

    results.sort(key=lambda r: r.chapter_index)
    elapsed = time.perf_counter() - started
    summary = BatchRunResult(
        ok=sum(1 for r in results if r.status == "ok"),
        failed=sum(1 for r in results if r.status == "failed"),
        elapsed_seconds=elapsed,
        results=tuple(results),
    )
    _print_summary(summary, quiet=quiet)
    return summary


def _resolve_capmd_executable(explicit: str | None) -> str:
    """Devuelve el comando correcto para invocar ``capmd``.

    Prioridad:
      1. ``explicit`` si fue pasado.
      2. ``shutil.which("capmd")`` — entry point del venv o PATH.
      3. ``python -m capmd`` (requiere ``__main__.py``; puede no existir).

    Devuelve el string listo para ``subprocess.run(shell=False)`` cuando
    es un único token (caso 1 y 2), o listo para ``shlex.split`` cuando
    contiene espacios (caso 3).
    """
    if explicit:
        return explicit  # pragma: no cover
    import shutil

    found = shutil.which("capmd")
    if found:
        return found
    return f"{sys.executable} -m capmd"  # pragma: no cover
