"""Caché de conversión de PDFs a Markdown (K6).

El comparador hashea (input_bytes + page_range + cleaner_config +
capmd_version) para identificar entradas de caché. Si la entrada
existe en el cache dir, se omite la conversión (subprocess markitdown,
cleaners, image extraction) y se devuelve el markdown cacheado. Las
imágenes cacheadas se restauran al output dir.

Cache activo por default; ``--no-cache`` o ``CAPMD_NO_CACHE=1`` lo
desactivan. Cache dir: ``$XDG_CACHE_HOME/capmd/convert/`` (default
``~/.cache/capmd/convert/``); override via ``--cache-dir`` o
``CAPMD_CACHE_DIR``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import capmd

__all__ = [
    "BUNDLE_VERSION",
    "CacheEntry",
    "ImageMeta",
    "cache_entry_path",
    "cache_images_dir",
    "compute_cache_key",
    "compute_cleaner_config_snapshot",
    "get_cache_dir",
    "load_cache_entry",
    "save_cache_entry",
    "should_use_cache",
]


BUNDLE_VERSION = "1"
"""Schema version del bundle JSON (incremental al romper compat)."""

# Snapshot fields que viajan al cache key. Si cambia cualquiera,
# el cache se invalida.
DEFAULT_CLEANERS: tuple[str, ...] = ()
DEFAULT_PIPELINE: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImageMeta:
    """Metadata de imagen cacheada (sin el binario en sí)."""

    name: str
    sha256: str
    relpath: str


@dataclass(frozen=True)
class CleanerConfigSnapshot:
    """Snapshot determinístico del pipeline de cleaners.

    El orden se normaliza (sorted) y el JSON canónico se serializa con
    ``sort_keys=True`` para que el hash sea estable entre runs.
    """

    enabled: tuple[str, ...] = DEFAULT_CLEANERS
    disabled: tuple[str, ...] = DEFAULT_CLEANERS
    pipeline: tuple[str, ...] = DEFAULT_PIPELINE

    def to_canonical_json(self) -> str:
        payload = {
            "enabled": list(self.enabled),
            "disabled": list(self.disabled),
            "pipeline": list(self.pipeline),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CacheEntry:
    """Bundle cacheado: metadata + payload de una corrida."""

    version: str
    key: str
    created_at: str
    capmd_version: str
    markdown: str
    fm: dict[str, Any] = field(default_factory=dict)
    images_meta: tuple[ImageMeta, ...] = ()
    images_dir: str = ""


# ---------------------------------------------------------------------------
# Cache key computation
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    """Devuelve sha256 hex (64 chars) sin uso criptográfico.

    ``usedforsecurity=False`` indica que es content addressing, no
    autenticación: queremos collision resistance (para deduplicar) y NO
    preimage resistance (no firmamos nada). Si dos inputs producen el
    mismo hash, simplemente re-corremos la conversión (no es seguridad).
    """
    return hashlib.sha256(data, usedforsecurity=False).hexdigest()


def compute_cleaner_config_snapshot(
    cleaners_enabled: tuple[str, ...] | None,
    cleaners_disabled: tuple[str, ...] | None,
    pipeline: tuple[str, ...] | None,
) -> CleanerConfigSnapshot:
    """Snapshot determinístico: ordena todos los tuplas."""
    return CleanerConfigSnapshot(
        enabled=tuple(sorted(cleaners_enabled or ())),
        disabled=tuple(sorted(cleaners_disabled or ())),
        pipeline=tuple(sorted(pipeline or ())),
    )


def compute_cache_key(
    *,
    pdf_bytes: bytes,
    page_range: str | None,
    cleaner_snapshot: CleanerConfigSnapshot,
    capmd_version: str,
) -> str:
    """Devuelve el sha256 hex (64 chars) que identifica el cache entry.

    Componentes del hash (todos hex):
    - sha256(pdf_bytes): hash del input.
    - sha256(page_range o ""): rango de páginas (normalizado).
    - sha256(cleaner_snapshot.to_canonical_json()): config de cleaners.
    - sha256(capmd_version): invalida caches viejos al upgrade.

    El hash final es ``sha256(``+``.join(components))``.
    """
    file_hash = _sha256_hex(pdf_bytes)
    range_hash = _sha256_hex(page_range.encode("utf-8") if page_range else b"")
    cleaner_hash = _sha256_hex(
        cleaner_snapshot.to_canonical_json().encode("utf-8")
    )
    version_hash = _sha256_hex(capmd_version.encode("utf-8"))

    combined = "|".join(
        [file_hash, range_hash, cleaner_hash, version_hash]
    ).encode("utf-8")
    return hashlib.sha256(combined, usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# Cache directory management
# ---------------------------------------------------------------------------


def _default_xdg_cache_home() -> Path:
    """Fallback XDG_CACHE_HOME: ``$XDG_CACHE_HOME`` o ``~/.cache``."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".cache"


def get_cache_dir(*, override: str | None = None) -> Path:
    """Resuelve el cache dir con prioridad:

    1. ``override`` (argumento ``--cache-dir``).
    2. Env var ``CAPMD_CACHE_DIR``.
    3. ``$XDG_CACHE_HOME/capmd/convert/``.
    4. ``~/.cache/capmd/convert/`` (fallback — respeta ``$HOME``).

    Crea el dir si no existe.

    Notas:
    - El fallback ``$HOME`` es importante para tests (aislar HOME a un
      tmpdir evita contaminar ``~/.cache/capmd/`` entre runs).
    - En macOS, ``XDG_CACHE_HOME`` usualmente NO está seteada y caemos
      al fallback ``~/Library/Caches/capmd/convert/`` (via ``$HOME``).
    - En CI (GitHub Actions), ``$HOME=/github/home`` y los caches viven
      entre runs, así que tests deben setear ``$XDG_CACHE_HOME=$RUNNER_TEMP``.
    """
    if override:
        cache_dir = Path(override).expanduser().resolve()
    else:
        env_dir = os.environ.get("CAPMD_CACHE_DIR")
        if env_dir:
            cache_dir = Path(env_dir).expanduser().resolve()
        else:
            cache_dir = _default_xdg_cache_home() / "capmd" / "convert"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def cache_entry_path(cache_dir: Path, key: str) -> Path:
    """Path al JSON bundle: ``<cache_dir>/<key>.json``."""
    return cache_dir / f"{key}.json"


def cache_images_dir(cache_dir: Path, key: str) -> Path:
    """Path al dir de imágenes cacheadas: ``<cache_dir>/<key>__images/``."""
    return cache_dir / f"{key}__images"


# ---------------------------------------------------------------------------
# Cache read / write
# ---------------------------------------------------------------------------


def load_cache_entry(cache_dir: Path, key: str) -> CacheEntry | None:
    """Lee el cache entry. Devuelve ``None`` si no existe, corrupto, o
    schema version mismatch. Loggea warning via ``logging`` en corruption.
    """
    from capmd.logging import get_logger

    logger = get_logger(__name__)
    entry_path = cache_entry_path(cache_dir, key)
    if not entry_path.is_file():
        return None

    try:
        raw = entry_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "cache bundle corrupto en %s: %s; regenerando",
            entry_path,
            exc,
        )
        return None

    if data.get("version") != BUNDLE_VERSION:
        logger.warning(
            "cache bundle version %s != %s en %s; regenerando",
            data.get("version"),
            BUNDLE_VERSION,
            entry_path,
        )
        return None

    try:
        images_meta_raw = data.get("images_meta", [])
        images_meta = tuple(
            ImageMeta(
                name=m["name"],
                sha256=m["sha256"],
                relpath=m["relpath"],
            )
            for m in images_meta_raw
        )
        return CacheEntry(
            version=data["version"],
            key=data["key"],
            created_at=data["created_at"],
            capmd_version=data["capmd_version"],
            markdown=data["markdown"],
            fm=data.get("fm", {}),
            images_meta=images_meta,
            images_dir=data.get("images_dir", ""),
        )
    except (KeyError, TypeError) as exc:
        logger.warning(
            "cache bundle mal formado en %s: %s; regenerando",
            entry_path,
            exc,
        )
        return None


def _atomic_write_text(path: Path, content: str) -> None:
    """Escribe ``content`` a ``path`` atómicamente (tmp + rename)."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def save_cache_entry(
    cache_dir: Path,
    key: str,
    *,
    markdown: str,
    fm: dict[str, Any],
    images: tuple[Path, ...] | None = None,
    images_relpaths: tuple[str, ...] | None = None,
    capmd_version: str | None = None,
) -> CacheEntry | None:
    """Persiste el entry al cache dir. Devuelve el entry escrito o ``None``
    si disk full / write falló (warning logged, no raise).

    - ``images``: paths **absolutos** a los binarios a copiar al
      ``<cache_dir>/<key>__images/<sha256>.<ext>``. Si un path no existe
      o falla la copia, se omite del bundle (warning logged).
    - ``images_relpaths`` (FIX-3): strings portables (relativas al
      chapter_dir o nombres de archivo) que se almacenan en
      ``images_meta[*].relpath``. Si no se provee, se usa el
      ``str(img_path)`` del path absoluto. El restore no usa este campo;
      solo es diagnóstico y para tests.

    El bundle también registra el sha256 de cada imagen copiada.
    """
    from capmd.logging import get_logger

    logger = get_logger(__name__)
    version = capmd_version or capmd.__version__
    images_dir_name = f"{key}__images"

    images_meta: list[ImageMeta] = []
    images_paths = images or ()

    # Crear dir de imágenes si hay imágenes.
    if images_paths:
        images_dir = cache_images_dir(cache_dir, key)
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "no se pudo crear cache images dir %s: %s; "
                "el entry se guarda sin imágenes",
                images_dir,
                exc,
            )
            images_paths = ()

        for idx, img_path in enumerate(images_paths):
            if not img_path.is_file():
                continue
            try:
                img_bytes = img_path.read_bytes()
            except OSError as exc:
                logger.warning(
                    "no se pudo leer imagen %s: %s", img_path, exc
                )
                continue
            img_sha = _sha256_hex(img_bytes)
            ext = img_path.suffix.lstrip(".") or "png"
            dest_name = f"{img_sha}.{ext}"
            dest = images_dir / dest_name
            if not dest.is_file():
                try:
                    shutil.copy2(img_path, dest)
                except OSError as exc:
                    logger.warning(
                        "no se pudo copiar %s a cache: %s", img_path, exc
                    )
                    continue
            # relpath: preferir el portable provisto por el caller.
            relpath = (
                images_relpaths[idx]
                if images_relpaths is not None and idx < len(images_relpaths)
                else str(img_path)
            )
            images_meta.append(
                ImageMeta(
                    name=img_path.name,
                    sha256=img_sha,
                    relpath=relpath,
                )
            )

    bundle = {
        "version": BUNDLE_VERSION,
        "key": key,
        "created_at": _now_iso(),
        "capmd_version": version,
        "markdown": markdown,
        "fm": fm,
        "images_meta": [
            {"name": m.name, "sha256": m.sha256, "relpath": m.relpath}
            for m in images_meta
        ],
        "images_dir": images_dir_name if images_meta else "",
    }

    entry_path = cache_entry_path(cache_dir, key)
    try:
        _atomic_write_text(
            entry_path, json.dumps(bundle, ensure_ascii=False, indent=2)
        )
    except OSError as exc:
        logger.warning(
            "no se pudo escribir cache bundle %s: %s", entry_path, exc
        )
        return None

    return CacheEntry(
        version=version,
        key=key,
        created_at=str(bundle["created_at"]),
        capmd_version=version,
        markdown=markdown,
        fm=fm,
        images_meta=tuple(images_meta),
        images_dir=images_dir_name if images_meta else "",
    )


# ---------------------------------------------------------------------------
# CLI activation helper
# ---------------------------------------------------------------------------


def should_use_cache(
    *,
    no_cache_flag: bool = False,
) -> bool:
    """Decide si el cache está habilitado para esta corrida.

    ``no_cache_flag=True`` → ``False``. ``CAPMD_NO_CACHE`` (1/true/yes,
    case-insensitive) → ``False``. Default: ``True``.
    """
    if no_cache_flag:
        return False
    return os.environ.get("CAPMD_NO_CACHE", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )
