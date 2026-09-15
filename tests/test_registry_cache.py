"""Tests del hook de lectura cacheada ``_read_outline_cached`` (G5).

Cubre el criterio literal del roadmap: si el registry tiene la
entrada, ``read_outline_with_fallback`` NO se invoca.

Los tests mockean ``capmd.cli.read_outline_with_fallback`` para
contar invocaciones, y pre-poblan el registry con fixtures conocidas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd import registry as registry_mod
from capmd.cli import _read_outline_cached
from capmd.models import Chapter
from capmd.registry import BookRecord, upsert_book


@pytest.fixture(autouse=True)
def _isolate_registry_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_mod, "REGISTRY_PATH", tmp_path / "registry.json")


@pytest.fixture
def outline_chapters() -> list[Chapter]:
    return [
        Chapter(title="Chapter 1: Getting Started", level=1, start_page=1, end_page=1, index=1),
        Chapter(title="Chapter 2: Ownership", level=1, start_page=10, end_page=10, index=2),
    ]


def _seed(
    sha: str,
    chapters: list[Chapter],
    *,
    toc_from_outline: bool = True,
) -> None:
    rec = BookRecord(
        sha256=sha,
        title="Cached Book",
        format="pdf",
        pages_total=100,
        toc=tuple(chapters),
        toc_from_outline=toc_from_outline,
        source_path="/tmp/cached.pdf",
        registered_at="2026-09-15T20:30:00Z",
        last_seen_at="2026-09-15T20:30:00Z",
        run_count=1,
    )
    upsert_book(rec)


def test_cache_hit_does_not_call_read_outline_with_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outline_chapters: list[Chapter],
) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake\n")
    sha = "a" * 64
    _seed(sha, outline_chapters)

    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> list[Chapter]:
        calls.append(1)
        return outline_chapters

    # ``_read_outline_cached`` hace ``from capmd.sources.pdf import
    # read_outline_with_fallback`` lazy: parchear ahí es suficiente.
    from capmd.sources import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    chapters, from_outline = _read_outline_cached(pdf, sha, registry_enabled=True)
    assert chapters == outline_chapters
    assert from_outline is True
    assert calls == []  # NO se invocó


def test_cache_miss_calls_read_outline_with_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outline_chapters: list[Chapter],
) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake\n")
    sha = "b" * 64  # no en registry

    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> list[Chapter]:
        calls.append(1)
        return outline_chapters

    from capmd.sources import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    chapters, from_outline = _read_outline_cached(pdf, sha, registry_enabled=True)
    assert chapters == outline_chapters
    assert from_outline is True
    assert calls == [1]


def test_cache_hit_with_heuristic_cached_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outline_chapters: list[Chapter],
) -> None:
    """Una entrada cacheada de la heurística (toc_from_outline=False) se respeta."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake\n")
    sha = "c" * 64
    _seed(sha, outline_chapters, toc_from_outline=False)

    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> list[Chapter]:
        calls.append(1)
        return outline_chapters

    from capmd.sources import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    _chapters, from_outline = _read_outline_cached(pdf, sha, registry_enabled=True)
    assert from_outline is False
    assert calls == []


def test_registry_disabled_always_calls_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outline_chapters: list[Chapter],
) -> None:
    """Con ``registry_enabled=False`` se ignora el cache y se llama al fallback."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake\n")
    sha = "d" * 64
    _seed(sha, outline_chapters)  # hay entrada

    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> list[Chapter]:
        calls.append(1)
        return outline_chapters

    from capmd.sources import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    _read_outline_cached(pdf, sha, registry_enabled=False)
    assert calls == [1]


def test_cache_miss_by_sha_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outline_chapters: list[Chapter],
) -> None:
    """Si el sha256 no matchea, NO hay cache hit, aunque haya entradas."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake\n")
    _seed("e" * 64, outline_chapters)  # entrada para sha e
    query_sha = "f" * 64  # sha distinto

    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> list[Chapter]:
        calls.append(1)
        return outline_chapters

    from capmd.sources import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    _read_outline_cached(pdf, query_sha, registry_enabled=True)
    assert calls == [1]


def test_empty_cache_treated_as_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outline_chapters: list[Chapter],
) -> None:
    """Si el registry no tiene la clave, NO es cache hit."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake\n")
    sha = "0" * 64

    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> list[Chapter]:
        calls.append(1)
        return []

    from capmd.sources import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    _read_outline_cached(pdf, sha, registry_enabled=True)
    assert calls == [1]


def test_no_sha_means_no_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outline_chapters: list[Chapter],
) -> None:
    """Sin sha256 no se hace lookup del registry (siempre fallback)."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake\n")
    _seed("1" * 64, outline_chapters)

    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> list[Chapter]:
        calls.append(1)
        return []

    from capmd.sources import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    _read_outline_cached(pdf, None, registry_enabled=True)
    assert calls == [1]
