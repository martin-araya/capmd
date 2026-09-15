"""Renderers para ``capmd config show`` (G4).

Dos formatos:

- :func:`render_table` — tabla ASCII con secciones (top-level, env vars
  activas, TOML sources, libros disponibles). Default.
- :func:`render_json` — JSON parseable con la misma información.

Ambos consumen un :class:`CapmdConfig` ya resuelto (incluyendo
``apply_book_profile`` si el usuario invocó ``config show --book X``).
"""

from __future__ import annotations

import json
import os
import textwrap
from typing import Any

from capmd.config import ENV_VARS, CapmdConfig
from capmd.registry import load_registry

__all__ = ["render_json", "render_table"]


def _value_repr(value: Any) -> str:
    if value is None:
        return "<unset>"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        return "[" + ", ".join(str(x) for x in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{" + ", ".join(f"{k}={v!r}" for k, v in value.items()) + "}"
    return str(value)


def _section_top_level(cfg: CapmdConfig) -> list[str]:
    """Top-level: tabla con (key, value, source)."""
    rows: list[tuple[str, str, str]] = [
        ("out_dir", _value_repr(cfg.out_dir), cfg.sources.get("out_dir", "default")),
        (
            "image_format",
            _value_repr(cfg.image_format),
            cfg.sources.get("image_format", "default"),
        ),
        (
            "page_offset",
            _value_repr(cfg.page_offset),
            cfg.sources.get("page_offset", "default"),
        ),
        (
            "cleaners_enabled",
            _value_repr(cfg.cleaners_enabled),
            cfg.sources.get("cleaners_enabled", "default"),
        ),
        (
            "cleaners_disabled",
            _value_repr(cfg.cleaners_disabled),
            cfg.sources.get("cleaners_disabled", "default"),
        ),
        (
            "image_overrides",
            _value_repr(cfg.image_overrides),
            cfg.sources.get("image_overrides", "default"),
        ),
    ]

    lines = ["Top-level:", ""]
    key_w = max(len("Key"), max(len(k) for k, _, _ in rows))
    val_w = max(len("Value"), max(len(v) for _, v, _ in rows))
    src_w = max(len("Source"), max(len(s) for _, _, s in rows))
    lines.append(
        f"  {'Key'.ljust(key_w)}  {'Value'.ljust(val_w)}  {'Source'.ljust(src_w)}"
    )
    lines.append(
        f"  {'-' * key_w}  {'-' * val_w}  {'-' * src_w}"
    )
    for k, v, s in rows:
        lines.append(f"  {k.ljust(key_w)}  {v.ljust(val_w)}  {s.ljust(src_w)}")
    return lines


def _section_sources(cfg: CapmdConfig) -> list[str]:
    lines = ["", "TOML sources (en orden de carga):", ""]
    if not cfg.source_paths:
        lines.append("  (ninguno)")
        return lines
    for i, path in enumerate(cfg.source_paths, start=1):
        lines.append(f"  {i}. {path}")
    return lines


def _section_env_active(cfg: CapmdConfig) -> list[str]:
    """Lista las CAPMD_* activas en ``os.environ``, marcándolas como
    aplicadas o no según ``cfg.sources``."""
    lines = ["", "Active env vars (CAPMD_*):", ""]
    set_vars = [v for v in ENV_VARS if v in os.environ]
    if not set_vars:
        lines.append("  (ninguna)")
        return lines
    field_by_var = {
        "CAPMD_OUT_DIR": "out_dir",
        "CAPMD_IMAGE_FORMAT": "image_format",
        "CAPMD_PAGE_OFFSET": "page_offset",
        "CAPMD_CLEANERS_ENABLED": "cleaners_enabled",
        "CAPMD_CLEANERS_DISABLED": "cleaners_disabled",
    }
    for var in set_vars:
        value = os.environ[var]
        field = field_by_var.get(var, "")
        applied = "applied" if cfg.sources.get(field) == "env" else "ignored"
        lines.append(f"  {var}={value}  [{applied}]")
    return lines


def _section_books(cfg: CapmdConfig) -> list[str]:
    lines = ["", "Books (perfiles disponibles):", ""]
    if not cfg.books:
        lines.append("  (ninguno)")
        return lines
    for name, profile in cfg.books.items():
        bits: list[str] = []
        if profile.page_offset is not None:
            bits.append(f"page_offset={profile.page_offset}")
        if profile.image_format is not None:
            bits.append(f"image_format={profile.image_format}")
        if profile.out_dir is not None:
            bits.append(f"out_dir={profile.out_dir}")
        if profile.cleaners_enabled is not None:
            bits.append(
                "cleaners.enabled=[" + ", ".join(profile.cleaners_enabled) + "]"
            )
        if profile.cleaners_disabled is not None:
            bits.append(
                "cleaners.disabled=[" + ", ".join(profile.cleaners_disabled) + "]"
            )
        if profile.title_pattern is not None:
            bits.append(f"title_pattern={profile.title_pattern!r}")
        if not bits:
            bits.append("(no overrides)")
        lines.append(f"  [{name}]")
        for b in bits:
            lines.append(f"    {b}")
    return lines


def _section_registry() -> list[str]:
    """Estado del registry de libros cacheados (G5)."""
    from capmd.registry import REGISTRY_PATH

    lines = ["", "Registry (caché de libros por sha256, G5):", ""]
    lines.append(f"  path: {REGISTRY_PATH}")
    if not REGISTRY_PATH.exists():
        lines.append("  (no existe — todavía no se convirtió ningún libro)")
        return lines
    try:
        registry = load_registry(REGISTRY_PATH)
    except Exception as exc:
        lines.append(f"  (error leyendo: {exc})")
        return lines
    lines.append(f"  books: {len(registry)}")
    if registry:
        newest = max(registry.values(), key=lambda r: r.last_seen_at)
        lines.append(
            f"  newest: {newest.last_seen_at}  ({newest.title!r}, sha256:{newest.sha256[:12]}…)"
        )
    return lines


def _registry_summary() -> dict[str, Any]:
    """Resumen JSON del registry (G5): path, count, exists."""
    from capmd.registry import REGISTRY_PATH

    exists = REGISTRY_PATH.exists()
    count = 0
    if exists:
        try:
            count = len(load_registry(REGISTRY_PATH))
        except Exception:
            count = 0
    return {
        "path": str(REGISTRY_PATH),
        "exists": exists,
        "count": count,
    }


def render_table(cfg: CapmdConfig) -> str:
    """Render ASCII de la config efectiva con trace de procedencia."""
    parts: list[str] = []
    parts.append("Effective configuration:")
    parts.append("")
    parts.extend(_section_top_level(cfg))
    parts.extend(_section_sources(cfg))
    parts.extend(_section_env_active(cfg))
    parts.extend(_section_books(cfg))
    parts.extend(_section_registry())
    return "\n".join(parts) + "\n"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def render_json(cfg: CapmdConfig) -> str:
    """Render JSON parseable de la config efectiva."""
    payload = {
        "top_level": {
            "out_dir": _json_safe(cfg.out_dir),
            "image_format": cfg.image_format,
            "page_offset": cfg.page_offset,
            "cleaners_enabled": _json_safe(cfg.cleaners_enabled),
            "cleaners_disabled": _json_safe(cfg.cleaners_disabled),
            "image_overrides": _json_safe(cfg.image_overrides),
            "sources": cfg.sources,
        },
        "toml_sources": [str(p) for p in cfg.source_paths],
        "books": {
            name: {
                k: _json_safe(v)
                for k, v in {
                    "page_offset": p.page_offset,
                    "image_format": p.image_format,
                    "out_dir": p.out_dir,
                    "cleaners_enabled": p.cleaners_enabled,
                    "cleaners_disabled": p.cleaners_disabled,
                    "title_pattern": p.title_pattern,
                    "image_overrides": p.image_overrides,
                }.items()
                if v is not None and v != () and v != {}
            }
            for name, p in cfg.books.items()
        },
        "active_env_vars": {
            var: os.environ[var]
            for var in ENV_VARS
            if var in os.environ
        },
        "registry": _registry_summary(),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _wrap_text(text: str, *, width: int = 80) -> str:
    """Reformatea ``text`` preservando saltos de párrafo al ancho ``width``.

    Helper público para cualquier consumidor que necesite envolver el
    output de :func:`render_table` para emails o pipes.
    """
    return "\n".join(
        "\n".join(textwrap.fill(p, width=width) for p in para.split("\n"))
        for para in text.split("\n\n")
    )
