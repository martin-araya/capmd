"""Loader de configuración TOML + env vars + entry points de integración.

Alcance (G1 + G2 + G3 del roadmap):
  - Carga ``~/.config/capmd/config.toml`` y ``./capmd.toml``.
  - Carga variables de entorno ``CAPMD_*`` (G2).
  - Carga perfiles de libro ``[books.\"<id>\"]`` (G3); activación por
    nombre (``--book <id>``) o por sha256 del PDF (auto-match).
  - Precedencia:
        defaults < global_toml < project_toml < env < book_profile < CLI
  - Claves top-level: ``out_dir``, ``image_format``, ``page_offset``,
    ``[cleaners].enabled/disabled``, ``[images]`` (compat E2).
  - ``load_config(env=None, *, project_toml, global_toml) -> CapmdConfig``
    con valores validados y defaults ya aplicados.
  - ``merge_configs(base, override)`` y ``apply_book_profile(cfg, profile)``
    para componer capas (públicos).

Fuera de alcance (G4+):
  - Subcomandos ``capmd config init/show`` (G4).
  - Caché por sha256 (G5).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from capmd.llm import build_llm_client
from capmd.logging import get_logger

__all__ = [
    "ENV_VARS",
    "GLOBAL_TOML",
    "PROJECT_TOML",
    "SHA256_PREFIX",
    "BookProfile",
    "CapmdConfig",
    "apply_book_profile",
    "build_llm_client",
    "find_profile_by_hash",
    "find_profile_by_name",
    "load_config",
    "load_image_filter_overrides",
    "merge_configs",
]

logger = get_logger(__name__)


ImageFormat = Literal["png", "webp"]


@dataclass(frozen=True)
class BookProfile:
    """Overrides por libro leídos de ``[books.\"<id>\"]``.

    Cada campo es opcional: ``None`` = "sin override" (no pisa el valor
    resuelto en :class:`CapmdConfig`). El ``name`` es el id literal del
    TOML (puede ser un nombre humano o un hash con prefijo
    ``sha256:``).

    Atributos:
        name: id del perfil (e.g. ``"rust-handbook"`` o ``"sha256:<hex>"``).
        page_offset: offset ``printed - physical`` (>= 0 o ``None``).
        image_format: ``"png"`` / ``"webp"`` o ``None``.
        out_dir: directorio de salida override o ``None``.
        cleaners_enabled: whitelist override (``None`` = sin override).
        cleaners_disabled: blacklist override (``None`` = sin override).
        image_overrides: subset de ``[images]`` por libro.
        title_pattern: regex source (compilable) para matching de
            ``--chapter``; ``None`` = sin override (usa substring).
    """

    name: str
    page_offset: int | None = None
    image_format: ImageFormat | None = None
    out_dir: Path | None = None
    cleaners_enabled: tuple[str, ...] | None = None
    cleaners_disabled: tuple[str, ...] | None = None
    image_overrides: dict[str, Any] = field(default_factory=dict)
    title_pattern: str | None = None


@dataclass(frozen=True)
class CapmdConfig:
    """Config de una capa; ya validada.

    Una capa puede ser la de defaults, la de un TOML, o la de env vars.
    Para componer capas se usa :func:`merge_configs`. Para aplicar un
    perfil de libro se usa :func:`apply_book_profile`.

    Atributos:
        out_dir: directorio de salida (``None`` = stdout). ``None``
            significa "sin override" para :func:`merge_configs`.
        image_format: ``"png"`` o ``"webp"``.
        page_offset: offset no-negativo.
        cleaners_enabled: si no es ``None``, lista blanca de cleaners.
        cleaners_disabled: si no es ``None``, lista negra de cleaners.
            Ambos no pueden valer no-None a la vez (el loader gana
            ``enabled``).
        image_overrides: subset de ``[images]`` con claves conocidas
            (``min_size``, ``repeat_threshold``,
            ``background_coverage``); compat con E2.
        books: ``{id: BookProfile}`` cargado del TOML (G3). No se
            mergea entre capas; se carga una sola vez desde los TOMLs.
        source_paths: rutas que aportaron datos, en orden, para
            ``config show`` futuro.
        sources: ``{field_name: layer_name}`` con la capa que aportó
            el valor FINAL de cada campo (e.g. ``{"page_offset":
            "project", "image_format": "env"}``). Usado por
            :mod:`capmd.config_show` (G4) para renderizar el trace
            de procedencia. ``layer_name`` ∈ ``{"default", "global",
            "project", "env", "book:<id>"}``. Campos que conservan el
            default tienen ``"default"``.
    """

    out_dir: Path | None
    image_format: ImageFormat
    page_offset: int
    cleaners_enabled: tuple[str, ...] | None
    cleaners_disabled: tuple[str, ...] | None
    image_overrides: dict[str, Any] = field(default_factory=dict)
    books: dict[str, BookProfile] = field(default_factory=dict)
    source_paths: tuple[Path, ...] = ()
    sources: dict[str, str] = field(default_factory=dict)


# Source-layer names used in CapmdConfig.sources.
SRC_DEFAULT: str = "default"
SRC_GLOBAL: str = "global"
SRC_PROJECT: str = "project"
SRC_ENV: str = "env"


GLOBAL_TOML: Path = Path.home() / ".config" / "capmd" / "config.toml"
PROJECT_TOML: Path = Path("capmd.toml")

SHA256_PREFIX: str = "sha256:"

ENV_VARS: tuple[str, ...] = (
    "CAPMD_OUT_DIR",
    "CAPMD_IMAGE_FORMAT",
    "CAPMD_PAGE_OFFSET",
    "CAPMD_CLEANERS_ENABLED",
    "CAPMD_CLEANERS_DISABLED",
)

_IMAGE_KEYS: frozenset[str] = frozenset(
    {"min_size", "repeat_threshold", "background_coverage"}
)

DEFAULTS: dict[str, Any] = {
    "out_dir": None,
    "image_format": "png",
    "page_offset": 0,
}


def _read_toml(path: Path) -> dict[str, Any] | None:
    """Lee un TOML completo; devuelve ``None`` si no existe o falla."""
    if not path.exists():
        return None
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        logger.debug("tomllib no disponible; saltando %s", path)  # pragma: no cover
        return None  # pragma: no cover
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("no se pudo leer %s: %s; usando defaults", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("%s no es una tabla TOML válida; ignorando", path)  # pragma: no cover
        return None  # pragma: no cover
    return data


def _validate_image_format(v: Any) -> ImageFormat:
    if isinstance(v, str) and v.lower() in {"png", "webp"}:
        return v.lower()  # type: ignore[return-value]
    logger.warning("image_format=%r inválido; usando 'png'", v)
    return "png"


def _validate_page_offset(v: Any) -> int:
    if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
        return v
    logger.warning("page_offset=%r inválido; usando 0", v)
    return 0


def _validate_out_dir(v: Any) -> Path | None:
    if v is None:
        return None
    if not isinstance(v, str):
        logger.warning("out_dir=%r inválido; usando None (stdout)", v)  # pragma: no cover
        return None  # pragma: no cover
    raw = v.strip()
    if not raw:
        return None  # pragma: no cover
    p = Path(raw).expanduser()
    if p.is_absolute() or raw.startswith(("./", "../", "..\\", ".\\")):
        return p
    logger.warning(  # pragma: no cover
        "out_dir=%r debe ser absoluto o relativo explícito ('./'/'../'); usando None",  # pragma: no cover
        v,  # pragma: no cover
    )  # pragma: no cover
    return None  # pragma: no cover


def _validate_cleaners(v: Any, *, key: str) -> tuple[str, ...]:
    from capmd.clean.pipeline import available_cleaner_names

    valid = set(available_cleaner_names())
    if not isinstance(v, list):
        logger.warning("cleaners.%s debe ser lista; ignorado", key)
        return ()
    out: list[str] = []
    for name in v:
        if isinstance(name, str) and name in valid:
            out.append(name)
        else:
            logger.warning(
                "cleaner %r desconocido (válidos: %s); ignorado",
                name,
                sorted(valid),
            )
    return tuple(out)


def _image_overrides_from(merged: dict[str, Any]) -> dict[str, Any]:
    section = merged.get("images", {})
    if not isinstance(section, dict):
        return {}  # pragma: no cover
    return {k: v for k, v in section.items() if k in _IMAGE_KEYS}


def _split_csv(raw: str) -> list[str]:
    """Split tipo CSV con ``,`` o ``;``; strip; ignora vacíos."""
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


def _cleaners_section_from(
    cleaners: dict[str, Any] | None,
) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    """Devuelve (enabled, disabled) saneadas; gana ``enabled`` si ambas."""
    if not isinstance(cleaners, dict):
        if cleaners is not None:
            logger.warning("cleaners debe ser tabla; ignorado")
        return None, None
    enabled = cleaners.get("enabled")
    disabled = cleaners.get("disabled")
    if enabled is not None and disabled is not None:
        logger.warning(
            "cleaners.enabled y cleaners.disabled presentes a la vez; usando solo enabled"
        )
        disabled = None
    out_enabled = _validate_cleaners(enabled, key="enabled") if enabled is not None else None
    out_disabled = (
        _validate_cleaners(disabled, key="disabled") if disabled is not None else None
    )
    return out_enabled, out_disabled


def _build_config_from_dict(
    merged: dict[str, Any],
    *,
    source_paths: tuple[Path, ...],
    layer_name: str,
    books: dict[str, BookProfile] | None = None,
) -> CapmdConfig:
    """Materializa un :class:`CapmdConfig` desde un dict estilo TOML/env.

    ``books`` se pasa por separado porque ``merged`` es un dict
    estilo-TOML del top-level; los perfiles viven bajo ``[books.*]`` y
    se parsean en :func:`_read_books_section`.

    ``layer_name`` se usa para poblar el campo ``sources``: cada key
    presente en ``merged`` (o que el validator haya podido colapsar al
    default de todas formas) se atribuye a esa capa. Keys ausentes en
    ``merged`` se marcan como ``SRC_DEFAULT``.
    """
    enabled, disabled = _cleaners_section_from(merged.get("cleaners"))
    sources: dict[str, str] = {}

    out_dir = _validate_out_dir(merged.get("out_dir", DEFAULTS["out_dir"]))
    sources["out_dir"] = layer_name if "out_dir" in merged else SRC_DEFAULT

    image_format = _validate_image_format(
        merged.get("image_format", DEFAULTS["image_format"])
    )
    sources["image_format"] = (
        layer_name if "image_format" in merged else SRC_DEFAULT
    )

    page_offset = _validate_page_offset(
        merged.get("page_offset", DEFAULTS["page_offset"])
    )
    sources["page_offset"] = (
        layer_name if "page_offset" in merged else SRC_DEFAULT
    )

    sources["cleaners_enabled"] = (
        layer_name if "cleaners" in merged and "enabled" in merged["cleaners"]
        else SRC_DEFAULT
    )
    sources["cleaners_disabled"] = (
        layer_name if "cleaners" in merged and "disabled" in merged["cleaners"]
        else SRC_DEFAULT
    )
    sources["image_overrides"] = (
        layer_name if "images" in merged else SRC_DEFAULT
    )

    return CapmdConfig(
        out_dir=out_dir,
        image_format=image_format,
        page_offset=page_offset,
        cleaners_enabled=enabled,
        cleaners_disabled=disabled,
        image_overrides=_image_overrides_from(merged),
        books=books if books is not None else {},
        source_paths=source_paths,
        sources=sources,
    )


def _validate_title_pattern(v: Any) -> str | None:
    """Devuelve el string si es un regex compilable; ``None`` si no.

    Un patrón inválido no rompe el loader — se loggea un warning y se
    trata como "sin override" (cae al substring default en el caller).
    """
    if not isinstance(v, str):
        return None
    import re

    try:
        re.compile(v, re.IGNORECASE)
    except re.error as exc:
        logger.warning("title_pattern=%r inválido (%s); ignorado", v, exc)
        return None
    return v


def _read_book_profile(name: str, table: dict[str, Any]) -> BookProfile | None:
    """Construye un :class:`BookProfile` desde una tabla TOML.

    Devuelve ``None`` si la tabla no contiene NINGUNA clave reconocible
    (perfil vacío → ignorado). Si la tabla tiene claves pero todas son
    inválidas, devuelve un perfil con defaults (no ``None``).
    """
    if not isinstance(table, dict):
        if table is not None:  # pragma: no cover
            logger.warning("[books.%s] debe ser tabla; ignorado", name)  # pragma: no cover
        return None  # pragma: no cover

    out_dir = _validate_out_dir(table.get("out_dir"))
    image_format_raw = table.get("image_format")
    image_format: ImageFormat | None
    if image_format_raw is None:
        image_format = None
    elif isinstance(image_format_raw, str) and image_format_raw.lower() in {"png", "webp"}:
        image_format = image_format_raw.lower()  # type: ignore[assignment]
    else:
        logger.warning("[books.%s].image_format=%r inválido; ignorado", name, image_format_raw)  # pragma: no cover
        image_format = None  # pragma: no cover

    offset_raw = table.get("page_offset")
    if offset_raw is None:
        page_offset: int | None = None
    elif isinstance(offset_raw, int) and not isinstance(offset_raw, bool) and offset_raw >= 0:
        page_offset = offset_raw
    else:
        logger.warning("[books.%s].page_offset=%r inválido; ignorado", name, offset_raw)  # pragma: no cover
        page_offset = None  # pragma: no cover

    enabled, disabled = _cleaners_section_from(table.get("cleaners"))
    image_overrides = _image_overrides_from(table)
    title_pattern = _validate_title_pattern(table.get("title_pattern"))

    # Si TODO es None, devolvemos None para no contaminar el registry.
    if (
        out_dir is None
        and image_format is None
        and page_offset is None
        and enabled is None
        and disabled is None
        and not image_overrides
        and title_pattern is None
    ):
        return None

    return BookProfile(
        name=name,
        page_offset=page_offset,
        image_format=image_format,
        out_dir=out_dir,
        cleaners_enabled=enabled,
        cleaners_disabled=disabled,
        image_overrides=image_overrides,
        title_pattern=title_pattern,
    )


def _read_books_section(merged: dict[str, Any]) -> dict[str, BookProfile]:
    """Lee ``merged['books']`` (si existe) y devuelve ``{name: profile}``.

    Project > global se aplica fuera (en el caller que mergea los dos
    TOMLs); esta función solo parsea el dict ya mergeado.
    """
    books_section = merged.get("books")
    if books_section is None:
        return {}
    if not isinstance(books_section, dict):
        logger.warning("[books] debe ser tabla; ignorado")
        return {}
    out: dict[str, BookProfile] = {}
    for name, table in books_section.items():
        if not isinstance(name, str) or not name:
            logger.warning("[books.%s] id inválido; ignorado", name)  # pragma: no cover
            continue  # pragma: no cover
        profile = _read_book_profile(name, table)
        if profile is not None:  # pragma: no cover
            out[name] = profile
    return out


def find_profile_by_name(
    books: dict[str, BookProfile], name: str
) -> BookProfile | None:
    """Lookup exacto por ``--book <name>``. Case-sensitive."""
    return books.get(name)


def find_profile_by_hash(
    books: dict[str, BookProfile], sha256_hex: str
) -> BookProfile | None:
    """Busca un perfil cuya clave sea ``f"{SHA256_PREFIX}{sha256_hex}"``.

    ``sha256_hex`` debe estar en hex (sin ``0x``, lowercase o uppercase).
    Una clave con prefijo ``sha256:`` que NO matchee 64 hex chars NO se
    trata como hash (puede ser un nombre de libro que comienza con
    ``sha256:``).
    """
    if not isinstance(sha256_hex, str):
        return None  # pragma: no cover
    if not sha256_hex:
        return None  # pragma: no cover
    key = f"{SHA256_PREFIX}{sha256_hex}"
    return books.get(key)


def apply_book_profile(cfg: CapmdConfig, profile: BookProfile) -> CapmdConfig:
    """Devuelve un nuevo :class:`CapmdConfig` con los campos non-None
    del perfil pisando los de ``cfg``.

    Mismo patrón que :func:`merge_configs` pero operando sobre un
    :class:`BookProfile`. El campo ``books`` se preserva tal cual
    (los perfiles no se anidan) y ``source_paths`` también.

    El campo ``sources`` se actualiza: cada field cuya fuente efectiva
    cambia de capa por acción del perfil se re-etiqueta como
    ``"book:<id>"``.
    """
    layer_name = f"book:{profile.name}"
    new_sources = dict(cfg.sources)

    if profile.out_dir is not None:
        new_sources["out_dir"] = layer_name  # pragma: no cover
    if profile.image_format is not None:
        new_sources["image_format"] = layer_name
    if profile.page_offset is not None:
        new_sources["page_offset"] = layer_name
    if profile.cleaners_enabled is not None:
        new_sources["cleaners_enabled"] = layer_name  # pragma: no cover
    if profile.cleaners_disabled is not None:
        new_sources["cleaners_disabled"] = layer_name
    if profile.image_overrides:
        new_sources["image_overrides"] = layer_name  # pragma: no cover

    return CapmdConfig(
        out_dir=profile.out_dir if profile.out_dir is not None else cfg.out_dir,
        image_format=(
            profile.image_format
            if profile.image_format is not None
            else cfg.image_format
        ),
        page_offset=(
            profile.page_offset
            if profile.page_offset is not None
            else cfg.page_offset
        ),
        cleaners_enabled=(
            profile.cleaners_enabled
            if profile.cleaners_enabled is not None
            else cfg.cleaners_enabled
        ),
        cleaners_disabled=(
            profile.cleaners_disabled
            if profile.cleaners_disabled is not None
            else cfg.cleaners_disabled
        ),
        image_overrides=(
            {**cfg.image_overrides, **profile.image_overrides}
            if profile.image_overrides
            else cfg.image_overrides
        ),
        books=cfg.books,
        source_paths=cfg.source_paths,
        sources=new_sources,
    )


def _read_env(env: Mapping[str, str]) -> dict[str, Any]:
    """Lee vars ``CAPMD_*``; devuelve dict parcial estilo TOML.

    - Variables no listadas en :data:`ENV_VARS` se ignoran.
    - Valores inválidos se loggean y caen a la capa inferior (el
      dict devuelto simplemente no incluye esa clave).
    """
    out: dict[str, Any] = {}

    if "CAPMD_OUT_DIR" in env:
        out["out_dir"] = env["CAPMD_OUT_DIR"]

    if "CAPMD_IMAGE_FORMAT" in env:
        raw_image = env["CAPMD_IMAGE_FORMAT"].strip()
        # Si el valor es válido, _validate_image_format lo normaliza;
        # si no, ya loggea el warning y devuelve el default. Acá
        # decidimos si pisa la capa inferior o no.
        if isinstance(raw_image, str) and raw_image.lower() in {"png", "webp"}:
            out["image_format"] = raw_image.lower()
        else:
            logger.warning(
                "CAPMD_IMAGE_FORMAT=%r inválido; ignorado", raw_image
            )

    if "CAPMD_PAGE_OFFSET" in env:
        raw_offset = env["CAPMD_PAGE_OFFSET"].strip()
        if not raw_offset:
            pass  # pragma: no cover
        elif not raw_offset.lstrip("-").isdigit():
            logger.warning("CAPMD_PAGE_OFFSET=%r no es int; ignorado", raw_offset)
        else:
            try:
                value = int(raw_offset)
                if value < 0:
                    logger.warning("CAPMD_PAGE_OFFSET=%r negativo; ignorado", raw_offset)  # pragma: no cover
                else:
                    out["page_offset"] = value
            except ValueError:  # pragma: no cover
                logger.warning("CAPMD_PAGE_OFFSET=%r no es int; ignorado", raw_offset)  # pragma: no cover

    cleaners: dict[str, list[str]] = {}
    for key, var in (
        ("enabled", "CAPMD_CLEANERS_ENABLED"),
        ("disabled", "CAPMD_CLEANERS_DISABLED"),
    ):
        if var in env:
            cleaners[key] = _split_csv(env[var])
    if cleaners:
        out["cleaners"] = cleaners

    return out


def merge_configs(base: CapmdConfig, override: CapmdConfig) -> CapmdConfig:
    """Compone dos configs: campos de ``override`` non-None (y no-default)
    ganan sobre ``base``.

    Semántica:
        - ``out_dir``: ``None`` en override = "sin cambio" (no pisa
          ``None`` legítimo de base).
        - ``image_format``: si override.image_format ==
          :data:`DEFAULTS`['image_format'], se considera "sin cambio"
          (para distinguir ``"png"`` legítimo vs "default").
          Esto es seguro porque el validator colapsa valores inválidos
          al default antes de llegar acá.
        - ``page_offset``: análogo, contra
          :data:`DEFAULTS`['page_offset'].
        - ``cleaners_enabled``/``cleaners_disabled``: ``None`` significa
          "sin cambio". Una tupla vacía = override explícito (whitelist/
          blacklist vacíos).
        - ``image_overrides``: merge superficial (``override`` gana en
          claves presentes).
        - ``books``: se preserva el de ``base``. Los perfiles viven
          solo en la capa TOML; no se propagan por env.
        - ``source_paths``: concatenación ``base + override``.
        - ``sources``: para cada field donde ``override`` aportó un
          valor (non-default/non-None), se copia el layer_name de
          ``override``; si no, se mantiene el de ``base``.

    Returns:
        Nuevo :class:`CapmdConfig`.
    """
    new_sources = dict(base.sources)

    new_out_dir = override.out_dir if override.out_dir is not None else base.out_dir
    if override.out_dir is not None:
        new_sources["out_dir"] = override.sources.get("out_dir", SRC_DEFAULT)

    new_image_format = (
        override.image_format
        if override.image_format != DEFAULTS["image_format"]
        else base.image_format
    )
    if override.image_format != DEFAULTS["image_format"]:
        new_sources["image_format"] = override.sources.get("image_format", SRC_DEFAULT)

    new_page_offset = (
        override.page_offset
        if override.page_offset != DEFAULTS["page_offset"]
        else base.page_offset
    )
    if override.page_offset != DEFAULTS["page_offset"]:
        new_sources["page_offset"] = override.sources.get("page_offset", SRC_DEFAULT)

    new_cleaners_enabled = (
        override.cleaners_enabled
        if override.cleaners_enabled is not None
        else base.cleaners_enabled
    )
    if override.cleaners_enabled is not None:
        new_sources["cleaners_enabled"] = override.sources.get(
            "cleaners_enabled", SRC_DEFAULT
        )

    new_cleaners_disabled = (
        override.cleaners_disabled
        if override.cleaners_disabled is not None
        else base.cleaners_disabled
    )
    if override.cleaners_disabled is not None:
        new_sources["cleaners_disabled"] = override.sources.get(
            "cleaners_disabled", SRC_DEFAULT
        )

    new_image_overrides = (
        {**base.image_overrides, **override.image_overrides}
        if override.image_overrides
        else base.image_overrides
    )
    if override.image_overrides:
        new_sources["image_overrides"] = override.sources.get(  # pragma: no cover
            "image_overrides", SRC_DEFAULT
        )

    return CapmdConfig(
        out_dir=new_out_dir,
        image_format=new_image_format,
        page_offset=new_page_offset,
        cleaners_enabled=new_cleaners_enabled,
        cleaners_disabled=new_cleaners_disabled,
        image_overrides=new_image_overrides,
        books=base.books,
        source_paths=base.source_paths + override.source_paths,
        sources=new_sources,
    )


def _load_toml_layer(
    *,
    project_toml: Path | None,
    global_toml: Path | None,
) -> tuple[list[tuple[dict[str, Any], Path]], list[Path]]:
    """Lee global y project por separado; devuelve ``[(data, path), ...]``
    en orden global → project, más la lista de paths efectivamente
    leídos (en el mismo orden). Permite atribuir cada clave a su TOML
    de origen al construir el ``CapmdConfig``.
    """
    layers: list[tuple[dict[str, Any], Path]] = []
    source_paths: list[Path] = []
    for path in (global_toml, project_toml):
        if path is None:
            continue
        data = _read_toml(path)
        if data is None:
            continue
        layers.append((data, path))
        source_paths.append(path)
    return layers, source_paths


def _detect_layer_name_for_key(
    key: str, layers: list[tuple[dict[str, Any], Path]]
) -> str:
    """Devuelve ``'project'`` o ``'global'`` según qué TOML aportó ``key``.

    ``layers`` está en orden global → project; el último que aporta gana.
    Si ninguno aporta, devuelve ``SRC_DEFAULT``.
    """
    layer_for = SRC_DEFAULT
    for data, path in layers:
        if key in data:
            layer_for = SRC_PROJECT if path.name == PROJECT_TOML.name else SRC_GLOBAL
    return layer_for


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    project_toml: Path | None = PROJECT_TOML,
    global_toml: Path | None = GLOBAL_TOML,
) -> CapmdConfig:
    """Carga configuración efectiva con precedencia:

        defaults < global_toml < project_toml < env

    - ``env=None`` (default) usa :data:`os.environ`. Pasar ``env={}``
      para saltar la capa env (útil en tests). Pasar un ``Mapping``
      custom para tests determinísticos.
    - ``project_toml=None`` o ``global_toml=None`` salta esa capa.
    - TOMLs inexistentes o malformados se ignoran con warning.
    - Env vars no listadas en :data:`ENV_VARS` se ignoran.
    - Valores inválidos en cualquier capa: warning + fallback a la
      capa inferior (no se rompe el resolve).

    La sección ``[books.*]`` se parsea una sola vez desde la capa
    TOML (project > global). No se mergea con env vars. Para activar
    un perfil, ver :func:`apply_book_profile`.
    """
    if env is None:
        env = os.environ

    toml_layers, toml_sources = _load_toml_layer(
        project_toml=project_toml, global_toml=global_toml
    )
    # Merge TOML keys for actual resolution. Per-key attribution is
    # computed by ``_detect_layer_name_for_key`` para ``sources``.
    merged: dict[str, Any] = {}
    for data, _path in toml_layers:
        merged.update(data)

    books = _read_books_section(merged)
    enabled, disabled = _cleaners_section_from(merged.get("cleaners"))
    sources: dict[str, str] = {}

    out_dir = _validate_out_dir(merged.get("out_dir", DEFAULTS["out_dir"]))
    image_format = _validate_image_format(
        merged.get("image_format", DEFAULTS["image_format"])
    )
    page_offset = _validate_page_offset(
        merged.get("page_offset", DEFAULTS["page_offset"])
    )

    sources["out_dir"] = (
        _detect_layer_name_for_key("out_dir", toml_layers)
        if "out_dir" in merged
        else SRC_DEFAULT
    )
    sources["image_format"] = (
        _detect_layer_name_for_key("image_format", toml_layers)
        if "image_format" in merged
        else SRC_DEFAULT
    )
    sources["page_offset"] = (
        _detect_layer_name_for_key("page_offset", toml_layers)
        if "page_offset" in merged
        else SRC_DEFAULT
    )

    cleaners_section = merged.get("cleaners")
    sources["cleaners_enabled"] = (
        _detect_layer_name_for_key("enabled", toml_layers)
        if (
            isinstance(cleaners_section, dict) and "enabled" in cleaners_section
        )
        else SRC_DEFAULT
    )
    sources["cleaners_disabled"] = (
        _detect_layer_name_for_key("disabled", toml_layers)
        if (
            isinstance(cleaners_section, dict) and "disabled" in cleaners_section
        )
        else SRC_DEFAULT
    )

    images_section = merged.get("images")
    sources["image_overrides"] = (
        _detect_layer_name_for_key("images", toml_layers)
        if images_section is not None
        else SRC_DEFAULT
    )

    base = CapmdConfig(
        out_dir=out_dir,
        image_format=image_format,
        page_offset=page_offset,
        cleaners_enabled=enabled,
        cleaners_disabled=disabled,
        image_overrides=_image_overrides_from(merged),
        books=books,
        source_paths=tuple(toml_sources),
        sources=sources,
    )

    env_merged = _read_env(env)
    if not env_merged:
        return base

    env_sources: dict[str, str] = {}
    for key in ("out_dir", "image_format", "page_offset"):
        if key in env_merged:
            env_sources[key] = SRC_ENV
        else:
            env_sources[key] = SRC_DEFAULT
    cleaners_section_env = env_merged.get("cleaners")
    env_sources["cleaners_enabled"] = (
        SRC_ENV
        if (
            isinstance(cleaners_section_env, dict)
            and "enabled" in cleaners_section_env
        )
        else SRC_DEFAULT
    )
    env_sources["cleaners_disabled"] = (
        SRC_ENV
        if (
            isinstance(cleaners_section_env, dict)
            and "disabled" in cleaners_section_env
        )
        else SRC_DEFAULT
    )
    # image_overrides from env: not exposed in current schema (TOML only).
    env_sources["image_overrides"] = SRC_DEFAULT

    env_enabled, env_disabled = _cleaners_section_from(cleaners_section_env)
    env_cfg = CapmdConfig(
        out_dir=_validate_out_dir(env_merged.get("out_dir", DEFAULTS["out_dir"])),
        image_format=_validate_image_format(
            env_merged.get("image_format", DEFAULTS["image_format"])
        ),
        page_offset=_validate_page_offset(
            env_merged.get("page_offset", DEFAULTS["page_offset"])
        ),
        cleaners_enabled=env_enabled,
        cleaners_disabled=env_disabled,
        image_overrides={},
        books=base.books,
        source_paths=(),
        sources=env_sources,
    )
    return merge_configs(base, env_cfg)


def load_image_filter_overrides(
    *,
    global_toml: Path | None = None,
    project_toml: Path | None = None,
) -> dict[str, Any]:
    """Compat shim para E2. Delegado a :func:`load_config`.

    Acepta los mismos kwargs que :func:`load_config` para que tests
    puedan apuntar a TOMLs en ``tmp_path`` sin contaminar el estado
    global. La capa env se respeta (``os.environ``).
    """
    cfg = load_config(
        global_toml=global_toml if global_toml is not None else GLOBAL_TOML,
        project_toml=project_toml if project_toml is not None else PROJECT_TOML,
    )
    return cfg.image_overrides
