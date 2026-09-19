"""Parser de la sintaxis de ``--pages`` (fase C4).

Sintaxis soportada (separadores: coma entre tokens, guion dentro de un
rango):

  - ``"45-78"``     -> páginas 45..78 inclusive
  - ``"45-"``       -> desde 45 hasta el final del documento
  - ``"30"``        -> solo la página 30
  - ``"-30"``       -> desde 1 hasta 30
  - ``"12,15,20-25"`` -> unión, deduplicada y ordenada

Errores:

  - Sintaxis malformada (vacío, ``"0"``, ``"5-3"``, ``"45--78"``, ``"-"``
    suelto, no numérico, comas mal puestas) -> ``ValueError``.
  - Alguna página resuelta fuera del documento -> ``RangeOutOfBounds``.
"""

from __future__ import annotations

from capmd.errors import RangeOutOfBounds
from capmd.models import PageRange

__all__ = ["parse_pages", "translate_spec"]


class _TokenParser:
    """Parser de un único token ``"N"``, ``"A-B"``, ``"A-"`` o ``"-B"``.

    Acumula lados abiertos (``start=None`` o ``end=None``) y los
    resuelve después con el ``total_pages``.
    """

    def __init__(self, token: str) -> None:
        self.raw = token
        self.start: int | None = None
        self.end: int | None = None
        self._parse()

    def _parse(self) -> None:
        parts = self.raw.split("-")
        if len(parts) > 2:
            raise ValueError(f"demasiados '-' en {self.raw!r}: se esperaba 'N', 'A-B', 'A-' o '-B'")

        if len(parts) == 1:
            self._set_both(parts[0], parts[0])
            return

        # len == 2: o "A-B" (cerrado), "A-" (abierto derecha) o "-B" (abierto izq).
        # El caso "-" suelto cae acá con dos strings vacíos.
        left, right = parts
        if not left and not right:
            raise ValueError(
                f"rango abierto en ambos lados {self.raw!r}: se esperaba 'A-B', 'A-' o '-B'"
            )

        if left:
            self._set_start(left)
        if right:
            self._set_end(right)

        # Si solo vino un lado, espejar.
        if self.start is None and self.end is not None:
            self.start = self.end
        if self.end is None and self.start is not None:
            self.end = self.start

    def _set_both(self, raw_start: str, raw_end: str) -> None:
        self._set_start(raw_start)
        self._set_end(raw_end)

    def _set_start(self, raw: str) -> None:
        try:
            n = int(raw)
        except ValueError as exc:
            raise ValueError(f"página no numérica en {self.raw!r}: {raw!r}") from exc
        if n < 1:
            raise ValueError(f"las páginas son 1-indexed; {n} no es válido ({self.raw!r})")
        self.start = n

    def _set_end(self, raw: str) -> None:
        try:
            n = int(raw)
        except ValueError as exc:  # pragma: no cover
            raise ValueError(f"página no numérica en {self.raw!r}: {raw!r}") from exc  # pragma: no cover
        if n < 1:
            raise ValueError(f"las páginas son 1-indexed; {n} no es válido ({self.raw!r})")  # pragma: no cover
        self.end = n

    def resolve(self, total_pages: int) -> tuple[int, int]:
        """Devuelve el rango cerrado ``(start, end)`` resuelto contra ``total_pages``.

        Lanza ``RangeOutOfBounds`` si la página resuelta supera el
        documento (caso de página fuera de rango), o ``ValueError``
        para errores de sintaxis (rango descendente, etc.).
        """
        assert self.start is not None and self.end is not None
        if self.end < self.start:
            raise ValueError(f"rango descendente en {self.raw!r}: {self.start} > {self.end}")
        opens_left = self.raw.startswith("-")
        opens_right = self.raw.endswith("-")
        start = 1 if opens_left else self.start
        end = total_pages if opens_right else self.end
        if start > total_pages:
            raise RangeOutOfBounds(
                f"página {start} fuera del documento (tiene {total_pages})",
                hint="revisá el spec de --pages o usá --page-offset si la numeración impresa difiere",
            )
        # FIX-5 / D5: también validar el extremo superior. Antes del fix,
        # ``--pages 1-99`` en un PDF de 18pp generaba ``range(1, 100)``
        # y pypdfium2 lanzaba ``IndexError`` raw al acceder a página 19.
        if end > total_pages:
            raise RangeOutOfBounds(
                f"--pages {start}-{end}: el PDF tiene {total_pages} páginas; "
                f"el rango válido es 1-{total_pages}",
                hint="ajustá el extremo superior (o usá --page-offset si la numeración impresa difiere)",
            )
        return start, end


def _tokenize(spec: str) -> list[str]:
    """Split por coma y strip whitespace. Tokens vacíos se descartan."""
    return [tok.strip() for tok in spec.split(",") if tok.strip()]


def parse_pages(spec: str, total_pages: int) -> PageRange:
    """Parsea el spec de ``--pages`` contra el total de páginas del documento.

    Devuelve un :class:`PageRange` con páginas ordenadas y únicas.
    """
    if total_pages < 1:
        raise ValueError(f"total_pages must be >= 1, got {total_pages}")
    if not spec or not spec.strip():
        raise ValueError("invalid page spec: vacío")

    pages: list[int] = []
    for token in _tokenize(spec):
        try:
            parser = _TokenParser(token)
            start, end = parser.resolve(total_pages)
        except ValueError as exc:
            raise ValueError(f"invalid page spec {spec!r}: {exc}") from None
        # ``RangeOutOfBounds`` se propaga sin envolver: ya tiene su
        # propio mensaje y exit_code (4).
        pages.extend(range(start, end + 1))

    if not pages:
        raise ValueError(f"invalid page spec {spec!r}: ningún token válido")  # pragma: no cover

    return PageRange(pages=tuple(sorted(set(pages))))


def translate_spec(spec: str, offset: int) -> str:
    """Devuelve el spec con cada número desplazado por ``offset``.

    Tokens abiertos (``"-"`` suelto, ``"45-"``, ``"-30"``) preservan su
    lado abierto: la traslación solo toca números explícitos.

    Sirve para que ``--page-offset`` traduzca el spec que el usuario
    escribe en paginación impresa al spec que ``parse_pages`` espera en
    paginación física, sin reimplementar la lógica de parseo.

    ``offset == 0`` es no-op (atajo). ``ValueError`` ante números no
    enteros (mismo criterio que ``parse_pages``).
    """
    if offset == 0:
        return spec
    if not spec:
        return spec  # pragma: no cover

    translated_tokens: list[str] = []
    for raw_token in spec.split(","):
        token = raw_token.strip()
        if not token:
            continue  # pragma: no cover
        parts = token.split("-", 1)
        new_parts: list[str] = []
        for part in parts:
            if part == "":
                new_parts.append("")
                continue
            try:
                shifted = int(part) + offset
            except ValueError as exc:
                raise ValueError(f"invalid page spec {spec!r}: número no entero {part!r}") from exc
            new_parts.append(str(shifted))
        translated_tokens.append("-".join(new_parts))

    return ",".join(translated_tokens)
