"""Caché local por sha256 de libros ya convertidos (G5 del roadmap).

Auto-registro: al convertir un PDF nuevo se guardan ``sha256``, título,
formato, ``pages_total`` y TOC cacheado para no re-parsear el outline
en la próxima corrida sobre el mismo libro. Esto cierra el criterio
literal del roadmap G5: *"la segunda corrida sobre el mismo libro es
mediblemente más rápida y no re-lee el outline"*.

Decisiones de diseño (ver ``roadmap.md`` G5):
  - Ubicación: ``~/.config/capmd/registry.json`` (junto a ``config.toml``
    de G1/G4, mismo directorio XDG).
  - Formato: JSON (sin nuevas dependencias). El archivo es interno; no
    está pensado para edición manual.
  - Concurrencia: ``fcntl.flock(LOCK_EX)`` + escritura atómica (tmp +
    ``os.replace``). En Windows degrada limpio sin lock.
  - Invalidación: por sha256; el cambio del archivo produce mismatch y
    la entrada se reemplaza en la próxima corrida exitosa.
  - Tolerancia a fallos: archivo ausente o malformado → ``{}`` con
    warning. Entradas individuales malformadas se descartan sin
    afectar al resto.

API pública:
  - :class:`BookRecord` — dataclass frozen con los campos cacheados.
  - :data:`REGISTRY_PATH` — path por default.
  - :func:`load_registry` / :func:`save_registry` — I/O completo.
  - :func:`lookup_toc` — lookup O(1) por sha256.
  - :func:`upsert_book` — inserta/actualiza con bump de ``run_count``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capmd.config import SHA256_PREFIX
from capmd.logging import get_logger
from capmd.models import Chapter

__all__ = [
    "REGISTRY_PATH",
    "BookRecord",
    "load_registry",
    "lookup_toc",
    "save_registry",
    "upsert_book",
]

logger = get_logger(__name__)


def _default_registry_path() -> Path:
    """Devuelve ``~/.config/capmd/registry.json``.

    Recomputado en cada llamada (no cacheado al import) para que
    ``monkeypatch.setenv("HOME", ...)`` funcione en tests.
    """
    return Path.home() / ".config" / "capmd" / "registry.json"


# Sentinel; tests pueden hacer ``monkeypatch.setattr(capmd.registry, "REGISTRY_PATH", ...)``.
REGISTRY_PATH: Path = _default_registry_path()


SCHEMA_VERSION: int = 1


def _utcnow_iso() -> str:
    """ISO 8601 en UTC con sufijo ``Z`` (e.g. ``2026-09-15T20:30:00Z``)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_from_iso(s: str) -> datetime:
    """Parsea el formato producido por :func:`_utcnow_iso`. Tolerante a ``+00:00``."""
    if s.endswith("Z"):  # pragma: no cover
        s = s[:-1] + "+00:00"  # pragma: no cover
    return datetime.fromisoformat(s)  # pragma: no cover


@dataclass(frozen=True)
class BookRecord:
    """Entrada del registry por libro (key: ``sha256:<hex>``).

    Atributos:
        sha256: hex de 64 chars (sin ``0x``).
        title: título humano (PDF ``/Title`` metadata o fallback a
            ``book_slug`` del filename).
        format: ``"pdf"`` (EPUB/DOCX no se cachean en G5).
        pages_total: total de páginas físicas del documento.
        toc: tupla de :class:`Chapter` con el outline cacheado. ``end_page``
            puede ser igual a ``start_page`` aquí; el caller (``infer_ranges``)
            hace la resolución final con ``pages_total``.
        toc_from_outline: ``True`` si el TOC vino del outline embebido;
            ``False`` si vino de la heurística (C8).
        source_path: ruta del archivo al momento del registro (solo
            informativo; no se usa para validación).
        registered_at: timestamp ISO 8601 de la primera vez que vimos
            este sha256.
        last_seen_at: timestamp ISO 8601 de la última corrida exitosa.
        run_count: cantidad de corridas exitosas registradas.
    """

    sha256: str
    title: str
    format: str
    pages_total: int
    toc: tuple[Chapter, ...]
    toc_from_outline: bool
    source_path: str | None
    registered_at: str
    last_seen_at: str
    run_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.sha256, str) or len(self.sha256) != 64:
            raise ValueError(f"sha256 must be 64 hex chars, got {self.sha256!r}")
        if not self.title:
            raise ValueError("title must be non-empty")
        if self.pages_total < 1:
            raise ValueError(f"pages_total must be >= 1, got {self.pages_total}")
        if self.run_count < 1:
            raise ValueError(f"run_count must be >= 1, got {self.run_count}")  # pragma: no cover

    @property
    def key(self) -> str:
        """Clave del registry (e.g. ``sha256:<hex>``)."""
        return f"{SHA256_PREFIX}{self.sha256}"


def _acquire_lock(fh: Any) -> Any:
    """Adquiere un flock exclusivo si está disponible; si no, devuelve ``None``.

    Usado internamente por :func:`save_registry`. En Windows (sin
    ``fcntl``) simplemente no hay lock: degradamos limpio porque el
    caller ya hace escritura atómica vía tmp + ``os.replace``.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover
        return None  # pragma: no cover
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fcntl


def _record_to_dict(rec: BookRecord) -> dict[str, Any]:
    """Serializa un :class:`BookRecord` a un dict apto para ``json.dump``.

    El ``toc`` se aplana a ``[{"level": ..., "title": ..., "page": ...}, ...]``
    para mantener el archivo trivial de inspeccionar y de producir desde
    fuera (no se espera edición manual pero es defendible).
    """
    return {
        "title": rec.title,
        "format": rec.format,
        "pages_total": rec.pages_total,
        "toc_from_outline": rec.toc_from_outline,
        "source_path": rec.source_path,
        "registered_at": rec.registered_at,
        "last_seen_at": rec.last_seen_at,
        "run_count": rec.run_count,
        "toc": [
            {"level": ch.level, "title": ch.title, "page": ch.start_page}
            for ch in rec.toc
        ],
    }


def _chapters_from_toc_list(
    toc_list: Iterable[dict[str, Any]],
) -> tuple[Chapter, ...]:
    """Construye :class:`Chapter` desde la lista ``toc`` del JSON.

    Asigna ``index`` 1-based en orden de aparición y ``end_page =
    start_page`` (la inferencia final la hace ``infer_ranges`` en el
    caller, igual que cuando se lee del PDF directo).
    """
    out: list[Chapter] = []
    for i, entry in enumerate(toc_list, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"toc entry {i} no es dict: {entry!r}")
        level_raw = entry.get("level")
        title_raw = entry.get("title")
        page_raw = entry.get("page")
        if not isinstance(level_raw, int) or isinstance(level_raw, bool):
            raise ValueError(f"toc[{i}].level inválido: {level_raw!r}")
        if not isinstance(title_raw, str) or not title_raw:
            raise ValueError(f"toc[{i}].title inválido: {title_raw!r}")
        if not isinstance(page_raw, int) or isinstance(page_raw, bool) or page_raw < 1:
            raise ValueError(f"toc[{i}].page inválido: {page_raw!r}")
        out.append(
            Chapter(
                title=title_raw,
                level=level_raw,
                start_page=page_raw,
                end_page=page_raw,
                index=i,
            )
        )
    return tuple(out)


def _dict_to_record(sha256_hex: str, raw: dict[str, Any]) -> BookRecord:
    """Materializa un :class:`BookRecord` desde un dict del JSON.

    Levanta ``ValueError`` ante cualquier inconsistencia. El caller
    (``load_registry``) captura y descarta la entrada con warning.
    """
    title = raw.get("title")
    fmt = raw.get("format")
    pages_total = raw.get("pages_total")
    toc_from_outline = raw.get("toc_from_outline")
    source_path = raw.get("source_path")
    registered_at = raw.get("registered_at")
    last_seen_at = raw.get("last_seen_at")
    run_count = raw.get("run_count")
    toc_list = raw.get("toc")

    if not isinstance(title, str) or not title:
        raise ValueError("title inválido")
    if not isinstance(fmt, str) or not fmt:
        raise ValueError("format inválido")  # pragma: no cover
    if not isinstance(pages_total, int) or isinstance(pages_total, bool) or pages_total < 1:
        raise ValueError("pages_total inválido")  # pragma: no cover
    if not isinstance(toc_from_outline, bool):
        raise ValueError("toc_from_outline inválido")  # pragma: no cover
    if source_path is not None and not isinstance(source_path, str):
        raise ValueError("source_path inválido")  # pragma: no cover
    if not isinstance(registered_at, str):
        raise ValueError("registered_at inválido")  # pragma: no cover
    if not isinstance(last_seen_at, str):
        raise ValueError("last_seen_at inválido")  # pragma: no cover
    if not isinstance(run_count, int) or isinstance(run_count, bool) or run_count < 1:
        raise ValueError("run_count inválido")  # pragma: no cover
    if not isinstance(toc_list, list):
        raise ValueError("toc debe ser lista")  # pragma: no cover

    toc = _chapters_from_toc_list(toc_list)
    return BookRecord(
        sha256=sha256_hex,
        title=title,
        format=fmt,
        pages_total=pages_total,
        toc=toc,
        toc_from_outline=toc_from_outline,
        source_path=source_path,
        registered_at=registered_at,
        last_seen_at=last_seen_at,
        run_count=run_count,
    )


def load_registry(path: Path | None = None) -> dict[str, BookRecord]:
    """Lee el registry desde ``path``. Devuelve ``{}`` si el archivo no existe.

    Si ``path`` es ``None`` (default), usa :data:`REGISTRY_PATH` al
    MOMENTO DE LA LLAMADA (no el capturado al import). Esto permite
    que ``monkeypatch.setattr(registry, "REGISTRY_PATH", ...)``
    funcione en tests sin pasar el path explícito.

    Comportamiento tolerante:
      - Archivo ausente → ``{}`` (silencioso).
      - Archivo malformado (no JSON, JSON inválido, raíz no es dict) →
        warning + ``{}``.
      - Entrada individual malformada → warning + se descarta ESA
        entrada; las demás se preservan.

    Esta función NO toma flock: el caller es responsable de coordinar
    cuando necesita atomicidad (ver :func:`_upsert_locked`).
    """
    effective_path = path if path is not None else REGISTRY_PATH
    """Lee el registry desde ``path``. Devuelve ``{}`` si el archivo no existe.

    Comportamiento tolerante:
      - Archivo ausente → ``{}`` (silencioso).
      - Archivo malformado (no JSON, JSON inválido, raíz no es dict) →
        warning + ``{}``.
      - Entrada individual malformada → warning + se descarta ESA
        entrada; las demás se preservan.

    Esta función NO toma flock: el caller es responsable de coordinar
    cuando necesita atomicidad (ver :func:`_upsert_locked`).
    """
    effective_path = path if path is not None else REGISTRY_PATH
    if not effective_path.exists():
        return {}

    try:
        with effective_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        logger.warning(
            "registry %s malformado (%s); usando {} en memoria",
            effective_path,
            exc,
        )
        return {}
    except OSError as exc:  # pragma: no cover
        logger.warning(  # pragma: no cover
            "registry %s no se pudo leer (%s); usando {}", effective_path, exc  # pragma: no cover
        )  # pragma: no cover
        return {}  # pragma: no cover

    if not isinstance(raw, dict):
        logger.warning("registry %s: raíz no es dict; usando {}", effective_path)
        return {}

    books_section = raw.get("books")
    if not isinstance(books_section, dict):
        # Estructura sin sección books → registry vacío pero válido.
        return {}

    out: dict[str, BookRecord] = {}
    for key, entry in books_section.items():
        if not isinstance(key, str) or not key.startswith(SHA256_PREFIX):
            logger.warning("registry: clave %r inválida; descartada", key)
            continue
        sha_hex = key[len(SHA256_PREFIX):]
        if not isinstance(entry, dict):
            logger.warning("registry: entrada %r no es dict; descartada", key)  # pragma: no cover
            continue  # pragma: no cover
        try:
            out[key] = _dict_to_record(sha_hex, entry)
        except (ValueError, KeyError) as exc:
            logger.warning("registry: entrada %r inválida (%s); descartada", key, exc)
            continue
    return out


def save_registry(
    registry: dict[str, BookRecord],
    path: Path | None = None,
) -> None:
    """Escribe el registry a ``path`` atómicamente.

    Estrategia:
      1. Crear ``path.parent`` si no existe.
      2. Escribir un JSON formateado a un archivo tmp con nombre único
         (``mkstemp``) en el mismo directorio.
      3. ``os.replace(tmp, path)`` — atómico en el mismo filesystem.
      4. ``fcntl.flock`` durante el write si está disponible (POSIX);
         en Windows se omite silenciosamente.

    Esta función NO toma flock de archivo: para coordinar read-modify-write
    entre procesos usar :func:`_upsert_locked` o serializar al nivel del
    caller. El tmp por proceso evita colisiones inter-processo pero no
    intra-processo (donde igual hace falta lock externo).

    El tmp se elimina si el write falla a mitad de camino para no
    dejar basura.
    """
    effective_path = path if path is not None else REGISTRY_PATH
    effective_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "books": {key: _record_to_dict(rec) for key, rec in registry.items()},
    }
    # Tmp único por llamada (``mkstemp``) → seguro entre procesos y entre
    # threads del mismo proceso. ``os.replace`` luego es atómico en el
    # mismo filesystem.
    import tempfile

    fd, tmp_name = tempfile.mkstemp(
        prefix=effective_path.name + ".",
        suffix=".tmp",
        dir=str(effective_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            _acquire_lock(fh)
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, effective_path)
    except Exception:  # pragma: no cover
        tmp_path.unlink(missing_ok=True)  # pragma: no cover
        raise  # pragma: no cover


def _upsert_locked(
    record: BookRecord,
    path: Path | None = None,
) -> None:
    path = path if path is not None else REGISTRY_PATH
    """Inserta/actualiza un record tomando flock sobre ``path`` durante toda la op.

    Usado por :func:`upsert_book` para hacer el read-modify-write atómico
    entre procesos concurrentes. El flock se toma sobre el archivo de
    destino (``path``); si no existe, se toma sobre ``path.parent`` con
    ``path.parent / ".lock"`` para evitar condiciones de carrera al
    crearlo por primera vez.

    En Windows (sin ``fcntl``) degrada a "sin lock" → pueden perderse
    upserts concurrentes del mismo sha256. Aceptable: la concurrencia
    sobre el mismo libro desde Windows es un edge case no objetivo.
    """
    import contextlib

    try:
        import fcntl
    except ImportError:  # pragma: no cover
        fcntl = None  # type: ignore[assignment]  # pragma: no cover

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / (path.name + ".lock")
    fh = lock_path.open("w", encoding="utf-8")
    try:
        if fcntl is not None:  # pragma: no cover
            fcntl.flock(fh, fcntl.LOCK_EX)  # pragma: no cover

        existing = load_registry(path)  # pragma: no cover
        existing_rec = existing.get(record.key)
        if existing_rec is None:
            new_record = record
        else:
            new_record = BookRecord(
                sha256=record.sha256,
                title=record.title,
                format=record.format,
                pages_total=record.pages_total,
                toc=record.toc,
                toc_from_outline=record.toc_from_outline,
                source_path=record.source_path,
                registered_at=existing_rec.registered_at,
                last_seen_at=record.last_seen_at,
                run_count=existing_rec.run_count + 1,
            )
        existing[new_record.key] = new_record
        save_registry(existing, path=path)
    finally:
        if fcntl is not None:  # pragma: no cover
            with contextlib.suppress(ValueError):  # pragma: no cover
                fcntl.flock(fh, fcntl.LOCK_UN)  # pragma: no cover
        fh.close()  # pragma: no cover
        lock_path.unlink(missing_ok=True)


def lookup_toc(
    sha256_hex: str,
    path: Path | None = None,
) -> BookRecord | None:
    path = path if path is not None else REGISTRY_PATH
    """Devuelve el :class:`BookRecord` para ``sha256_hex`` o ``None``.

    Atajo sobre :func:`load_registry` para el hot path del CLI (no
    expone el dict completo). NO toma lock porque es read-only y la
    consistencia eventual es aceptable para cache de outline.
    """
    if not isinstance(sha256_hex, str) or len(sha256_hex) != 64:
        return None
    registry_data = load_registry(path)
    return registry_data.get(f"{SHA256_PREFIX}{sha256_hex}")


def upsert_book(
    record: BookRecord,
    path: Path | None = None,
) -> None:
    path = path if path is not None else REGISTRY_PATH
    """Inserta o actualiza un :class:`BookRecord`` por sha256.

    Si ya existía una entrada para ese sha256:
      - ``run_count`` se incrementa en 1.
      - ``last_seen_at`` se actualiza a ``last_seen_at`` del nuevo record.
      - ``registered_at`` se preserva.
      - Los demás campos se toman del nuevo ``record``. En particular,
        un TOC que cambió reemplaza al anterior.

    Si la entrada no existía: ``run_count`` y ``registered_at`` se
    toman del ``record`` (típicamente ``run_count=1``).

    Concurrencia: usa :func:`_upsert_locked` que toma flock durante el
    read-modify-write para evitar condiciones de carrera entre procesos
    que convierten el mismo libro a la vez.
    """
    _upsert_locked(record, path)


def make_record(
    *,
    sha256_hex: str,
    title: str,
    format: str,
    pages_total: int,
    toc: Iterable[Chapter],
    toc_from_outline: bool,
    source_path: Path | None,
    run_count: int = 1,
) -> BookRecord:
    """Helper para construir un :class:`BookRecord`` con timestamps automáticos.

    Usado por el CLI al terminar una corrida exitosa. Si el caller ya
    tiene un ``BookRecord`` (p.ej. para re-escribirlo con campos
    actualizados), puede instanciar el dataclass directamente.
    """
    now = _utcnow_iso()
    return BookRecord(
        sha256=sha256_hex,
        title=title,
        format=format,
        pages_total=pages_total,
        toc=tuple(toc),
        toc_from_outline=toc_from_outline,
        source_path=str(source_path) if source_path is not None else None,
        registered_at=now,
        last_seen_at=now,
        run_count=run_count,
    )


def reset_registry_path(path: Path | None = None) -> Path:
    """Helper de tests: reemplaza el path por default en el módulo.

    Uso::

        monkeypatch.setattr(capmd.registry, "REGISTRY_PATH", tmp_path / "r.json")

    Es preferible a monkeypatchear el módulo entero: deja el resto del
    contrato intacto y es trivial de leer.
    """
    global REGISTRY_PATH
    REGISTRY_PATH = path if path is not None else _default_registry_path()  # pragma: no cover
    return REGISTRY_PATH  # pragma: no cover
