"""Generador del TOML starter para ``capmd config init`` (G4).

Devuelve el contenido del archivo de configuración ``capmd.toml``
completamente comentado. El usuario descomenta/ajusta las claves que
necesite; capmd las carga según la precedencia CLI > env > project >
global > defaults.
"""

from __future__ import annotations


def render_default_toml(*, target: str = "project") -> str:
    """Devuelve el contenido de un ``capmd.toml`` starter.

    ``target`` es informativo (se usa solo para el comentario del
    header); no afecta al contenido. Valores aceptados: ``"project"``
    o ``"global"`` (cualquier otro se trata como ``"project"``).
    """
    header = (
        "# ~/.config/capmd/config.toml — defaults globales para capmd.\n"
        if target == "global"
        else "# ./capmd.toml — defaults por proyecto para capmd.\n"
    )
    return (
        header
        + (
            "# CLI > env (CAPMD_*) > project > global > defaults.\n"
            "# Cualquier clave es opcional; descomentá la que apliquemos.\n"
            "\n"
            "# Directorio de salida por defecto (equivale a --out). null = stdout.\n"
            "# out_dir = \"~/Documents/capmd\"\n"
            "\n"
            "# Formato de imagen por defecto ('png' | 'webp').\n"
            "# image_format = \"png\"\n"
            "\n"
            "# Offset printed -> physical para --pages y rangos de --chapter.\n"
            "# page_offset = 0\n"
            "\n"
            "# Cleaners. Elegí UNO (no ambos).\n"
            "# [cleaners]\n"
            "# enabled = [\"whitespace\", \"headers\"]      # lista blanca\n"
            "# disabled = [\"page_numbers\"]              # lista negra\n"
            "\n"
            "# Imágenes (compat con filtros E2).\n"
            "# [images]\n"
            "# min_size = \"64x64\"\n"
            "# repeat_threshold = 0.8\n"
            "# background_coverage = 0.85\n"
            "\n"
            "# Perfiles por libro. Activar con --book <id> o auto-match por sha256.\n"
            "# [books.\"rust-handbook\"]\n"
            "# page_offset = 2\n"
            "# image_format = \"webp\"\n"
            "# title_pattern = \"^Chapter\\\\s+\\\\d+\"     # regex case-insensitive\n"
            "#\n"
            "# [books.\"rust-handbook\".cleaners]\n"
            "# disabled = [\"page_numbers\"]\n"
        )
    )


__all__ = ["render_default_toml"]
