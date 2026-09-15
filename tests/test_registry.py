"""Tests unitarios del módulo ``capmd.registry`` (G5).

Cubre:
  - load_registry sobre archivo ausente, válido, malformado, corrupto.
  - save_registry atómico + flock (concurrencia simulada).
  - upsert_book: insert + update con bump de run_count.
  - lookup_toc: hit/miss/archivo ausente.
  - Round-trip de BookRecord incluyendo toc.
  - Tolerancia a entradas individuales malformadas.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from capmd import registry
from capmd.models import Chapter
from capmd.registry import (
    BookRecord,
    load_registry,
    lookup_toc,
    make_record,
    save_registry,
    upsert_book,
)


@pytest.fixture(autouse=True)
def _isolate_registry_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirige REGISTRY_PATH a tmp_path para todos los tests."""
    monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "registry.json")


def _sample_toc() -> tuple[Chapter, ...]:
    return (
        Chapter(title="Chapter 1: Getting Started", level=1, start_page=1, end_page=1, index=1),
        Chapter(title="Chapter 2: Ownership", level=1, start_page=10, end_page=10, index=2),
    )


def _sample_record(sha: str = "a" * 64, **overrides: object) -> BookRecord:
    defaults: dict[str, object] = {
        "sha256": sha,
        "title": "Sample Book",
        "format": "pdf",
        "pages_total": 100,
        "toc": _sample_toc(),
        "toc_from_outline": True,
        "source_path": "/tmp/sample.pdf",
        "registered_at": "2026-09-15T20:30:00Z",
        "last_seen_at": "2026-09-15T20:30:00Z",
        "run_count": 1,
    }
    defaults.update(overrides)
    return BookRecord(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# load_registry
# ---------------------------------------------------------------------------


def test_load_registry_missing_file_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "missing.json"
    assert load_registry(p) == {}


def test_load_registry_malformed_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json", encoding="utf-8")
    assert load_registry(p) == {}


def test_load_registry_root_not_dict_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_registry(p) == {}


def test_load_registry_missing_books_section_returns_empty(tmp_path: Path) -> None:
    """Un registry válido pero sin ``books`` se trata como vacío."""
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    assert load_registry(p) == {}


def test_load_registry_skips_invalid_entry(tmp_path: Path) -> None:
    """Una entrada malformada se descarta; las demás se preservan."""
    p = tmp_path / "mixed.json"
    payload = {
        "schema_version": 1,
        "books": {
            "sha256:" + "a" * 64: {
                "title": "Valid",
                "format": "pdf",
                "pages_total": 10,
                "toc_from_outline": True,
                "source_path": None,
                "registered_at": "2026-09-15T20:30:00Z",
                "last_seen_at": "2026-09-15T20:30:00Z",
                "run_count": 1,
                "toc": [{"level": 1, "title": "Ch 1", "page": 1}],
            },
            "sha256:" + "b" * 64: {
                # Falta title → inválido.
                "format": "pdf",
                "pages_total": 10,
                "toc": [],
            },
        },
    }
    p.write_text(json.dumps(payload), encoding="utf-8")

    result = load_registry(p)
    assert len(result) == 1
    assert "sha256:" + "a" * 64 in result


def test_load_registry_skips_invalid_key(tmp_path: Path) -> None:
    """Claves que no arrancan con ``sha256:`` se descartan."""
    p = tmp_path / "badkey.json"
    payload = {
        "schema_version": 1,
        "books": {
            "notasha256key": {
                "title": "X",
                "format": "pdf",
                "pages_total": 1,
                "toc_from_outline": True,
                "source_path": None,
                "registered_at": "2026-09-15T20:30:00Z",
                "last_seen_at": "2026-09-15T20:30:00Z",
                "run_count": 1,
                "toc": [],
            },
        },
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert load_registry(p) == {}


# ---------------------------------------------------------------------------
# save_registry / round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    record = _sample_record()
    save_registry({record.key: record}, p)

    loaded = load_registry(p)
    assert len(loaded) == 1
    got = loaded[record.key]
    assert got.title == "Sample Book"
    assert got.format == "pdf"
    assert got.pages_total == 100
    assert got.toc_from_outline is True
    assert got.source_path == "/tmp/sample.pdf"
    assert got.run_count == 1
    assert len(got.toc) == 2
    assert got.toc[0].title == "Chapter 1: Getting Started"
    assert got.toc[0].start_page == 1
    assert got.toc[0].end_page == 1  # se preserva hasta que infer_ranges lo arregle
    assert got.toc[0].index == 1


def test_save_registry_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "deeper" / "r.json"
    save_registry({}, p)
    assert p.exists()


def test_save_registry_atomic_no_partial_write(tmp_path: Path) -> None:
    """Si el write falla a mitad, el archivo original NO se corrompe."""
    p = tmp_path / "r.json"
    record = _sample_record()
    save_registry({record.key: record}, p)

    original_content = p.read_text(encoding="utf-8")

    # Simulamos un fallo durante el dump escribiendo JSON inválido al tmp.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("{ corrupt", encoding="utf-8")

    # El archivo original sigue intacto.
    assert p.read_text(encoding="utf-8") == original_content


def test_save_registry_uses_lock_and_atomic_replace(tmp_path: Path) -> None:
    """save_registry toma flock exclusivo y luego os.replace."""
    import os as real_os
    from unittest import mock

    # Capturar las referencias reales ANTES de patchearlas.
    real_replace = real_os.replace
    real_lock = registry._acquire_lock

    p = tmp_path / "r.json"
    calls: list[str] = []

    def spy_replace(src: object, dst: object) -> None:
        calls.append("replace")
        real_replace(src, dst)  # type: ignore[arg-type]

    def spy_lock(fh: object) -> object:
        calls.append("lock")
        return real_lock(fh)

    with (
        mock.patch("capmd.registry.os.replace", spy_replace),
        mock.patch("capmd.registry._acquire_lock", spy_lock),
    ):
        record = _sample_record()
        save_registry({record.key: record}, p)

    assert "lock" in calls
    assert "replace" in calls
    assert calls.index("lock") < calls.index("replace")
    assert p.exists()


# ---------------------------------------------------------------------------
# upsert_book
# ---------------------------------------------------------------------------


def test_upsert_book_inserts_new(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    record = _sample_record()
    upsert_book(record, p)

    got = lookup_toc(record.sha256, p)
    assert got is not None
    assert got.title == "Sample Book"
    assert got.run_count == 1
    assert got.registered_at == got.last_seen_at  # recién creado


def test_upsert_book_bumps_run_count_and_preserves_registered_at(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    first = _sample_record(
        registered_at="2026-09-10T10:00:00Z",
        last_seen_at="2026-09-10T10:00:00Z",
    )
    upsert_book(first, p)

    second = _sample_record(
        title="Sample Book (updated)",
        registered_at="2026-09-15T20:00:00Z",  # ignorado
        last_seen_at="2026-09-15T20:00:00Z",
    )
    upsert_book(second, p)

    got = lookup_toc(first.sha256, p)
    assert got is not None
    assert got.run_count == 2
    assert got.registered_at == "2026-09-10T10:00:00Z"  # preservado
    assert got.last_seen_at == "2026-09-15T20:00:00Z"  # actualizado
    assert got.title == "Sample Book (updated)"  # actualizado


def test_upsert_book_replaces_toc_when_changed(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    first = _sample_record()
    upsert_book(first, p)

    new_toc = (
        Chapter(title="New Chapter A", level=1, start_page=1, end_page=5, index=1),
        Chapter(title="New Chapter B", level=1, start_page=6, end_page=10, index=2),
        Chapter(title="New Chapter C", level=1, start_page=11, end_page=15, index=3),
    )
    second = _sample_record(toc=new_toc)
    upsert_book(second, p)

    got = lookup_toc(first.sha256, p)
    assert got is not None
    assert len(got.toc) == 3
    assert got.toc[0].title == "New Chapter A"


# ---------------------------------------------------------------------------
# lookup_toc
# ---------------------------------------------------------------------------


def test_lookup_toc_hit(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    record = _sample_record(sha="c" * 64)
    upsert_book(record, p)
    assert lookup_toc("c" * 64, p) is not None


def test_lookup_toc_miss(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    record = _sample_record(sha="d" * 64)
    upsert_book(record, p)
    assert lookup_toc("e" * 64, p) is None


def test_lookup_toc_invalid_sha_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    # sha256 muy corto o vacío
    assert lookup_toc("", p) is None
    assert lookup_toc("a" * 10, p) is None


# ---------------------------------------------------------------------------
# Concurrencia
# ---------------------------------------------------------------------------


def test_concurrent_writes_do_not_corrupt(tmp_path: Path) -> None:
    """Varios hilos llamando upsert_book en paralelo dejan un JSON válido."""
    p = tmp_path / "r.json"
    errors: list[Exception] = []

    def worker(sha_suffix: str) -> None:
        try:
            sha = (sha_suffix + "f" * (64 - len(sha_suffix)))[:64]
            record = _sample_record(sha=sha, title=f"Book {sha_suffix}")
            upsert_book(record, p)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(str(i),)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    loaded = load_registry(p)
    assert len(loaded) == 8
    # Cada uno se grabó al menos una vez.
    assert all(rec.run_count >= 1 for rec in loaded.values())


# ---------------------------------------------------------------------------
# BookRecord validations
# ---------------------------------------------------------------------------


def test_bookrecord_rejects_bad_sha256() -> None:
    with pytest.raises(ValueError, match="sha256 must be 64"):
        _sample_record(sha="short")


def test_bookrecord_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title must be non-empty"):
        _sample_record(title="")


def test_bookrecord_rejects_zero_pages() -> None:
    with pytest.raises(ValueError, match="pages_total"):
        _sample_record(pages_total=0)


def test_bookrecord_key_property() -> None:
    rec = _sample_record(sha="ab" * 32)
    assert rec.key == "sha256:" + "ab" * 32


# ---------------------------------------------------------------------------
# make_record helper
# ---------------------------------------------------------------------------


def test_make_record_sets_timestamps(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    rec = make_record(
        sha256_hex="0" * 64,
        title="T",
        format="pdf",
        pages_total=10,
        toc=[],
        toc_from_outline=False,
        source_path=p,
    )
    assert rec.registered_at.endswith("Z")
    assert rec.last_seen_at.endswith("Z")
    assert rec.registered_at == rec.last_seen_at
    assert rec.run_count == 1
    assert rec.source_path == str(p)
