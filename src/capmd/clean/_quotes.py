"""Comillas tipográficas exóticas y sus reemplazos ASCII.

Las curly estándar U+2018–U+201D se preservan: son las que aparecen en
libros impresos modernos y se ven correctas en el output markdown. Solo
se normalizan las variantes raras listadas abajo.
"""

from __future__ import annotations

__all__ = ["RARE_QUOTES_MAP", "STANDARD_CURLY_QUOTES"]

RARE_QUOTES_MAP: dict[str, str] = {
    "‚": ",",  # U+201A SINGLE LOW-9 QUOTATION MARK
    "‛": "'",  # U+201B SINGLE HIGH-REVERSED-9 QUOTATION MARK
    "„": '"',  # U+201E DOUBLE LOW-9 QUOTATION MARK
    "‟": '"',  # U+201F DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    "′": "'",  # U+2032 PRIME
    "″": '"',  # U+2033 DOUBLE PRIME
    "‴": "'''",  # U+2034 TRIPLE PRIME
    "‵": "'",  # U+2035 REVERSED PRIME
    "‶": '"',  # U+2036 REVERSED DOUBLE PRIME
    "«": '"',  # U+00AB LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
    "»": '"',  # U+00BB RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
    "‹": "'",  # U+2039 SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    "›": "'",  # U+203A SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    "ʼ": "'",  # U+02BC MODIFIER LETTER APOSTROPHE
    "ʻ": "'",  # U+02BB MODIFIER LETTER TURNED COMMA
}

STANDARD_CURLY_QUOTES: frozenset[str] = frozenset(
    {
        "\u2018",  # LEFT SINGLE QUOTATION MARK
        "\u2019",  # RIGHT SINGLE QUOTATION MARK
        "\u201c",  # LEFT DOUBLE QUOTATION MARK
        "\u201d",  # RIGHT DOUBLE QUOTATION MARK
    }
)
