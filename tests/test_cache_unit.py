"""Tests unitarios de ``capmd.cache`` (K6).

Cubre:
- Hash determinístico + sensibility a cada componente.
- Snapshot del pipeline normaliza orden.
- get_cache_dir priority: override > env > XDG > default.
- save/load roundtrip.
- Schema version mismatch → None.
- JSON corrupto → None + warning.
- Atomic write + image copy.
- should_use_cache (default, --no-cache, env var).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capmd.cache import (
    BUNDLE_VERSION,
    CleanerConfigSnapshot,
    compute_cache_key,
    compute_cleaner_config_snapshot,
    get_cache_dir,
    load_cache_entry,
    save_cache_entry,
    should_use_cache,
)

# ---------------------------------------------------------------------------
# compute_cache_key
# ---------------------------------------------------------------------------


def _snap(
    enabled: tuple[str, ...] = (),
    disabled: tuple[str, ...] = (),
    pipeline: tuple[str, ...] = (),
) -> CleanerConfigSnapshot:
    return compute_cleaner_config_snapshot(enabled, disabled, pipeline)


def test_cache_key_deterministic() -> None:
    """Mismo input → mismo key."""
    snap = _snap(enabled=("headers",), disabled=("hyphens",))
    k1 = compute_cache_key(
        pdf_bytes=b"a", page_range="1-5",
        cleaner_snapshot=snap, capmd_version="0.1.0",
    )
    k2 = compute_cache_key(
        pdf_bytes=b"a", page_range="1-5",
        cleaner_snapshot=snap, capmd_version="0.1.0",
    )
    assert k1 == k2
    assert len(k1) == 64


def test_cache_key_changes_on_pdf_bytes() -> None:
    """PDF bytes diferentes → key diferente."""
    snap = _snap()
    k1 = compute_cache_key(pdf_bytes=b"a", page_range=None,
                          cleaner_snapshot=snap, capmd_version="0.1.0")
    k2 = compute_cache_key(pdf_bytes=b"b", page_range=None,
                          cleaner_snapshot=snap, capmd_version="0.1.0")
    assert k1 != k2


def test_cache_key_changes_on_page_range() -> None:
    """Page range diferente → key diferente."""
    snap = _snap()
    k1 = compute_cache_key(pdf_bytes=b"a", page_range="1-5",
                          cleaner_snapshot=snap, capmd_version="0.1.0")
    k2 = compute_cache_key(pdf_bytes=b"a", page_range="6-10",
                          cleaner_snapshot=snap, capmd_version="0.1.0")
    k3 = compute_cache_key(pdf_bytes=b"a", page_range=None,
                          cleaner_snapshot=snap, capmd_version="0.1.0")
    assert k1 != k2
    assert k1 != k3
    assert k2 != k3


def test_cache_key_changes_on_cleaner_config() -> None:
    """Config de cleaners diferente → key diferente."""
    pdf = b"a"
    k1 = compute_cache_key(pdf_bytes=pdf, page_range=None,
                          cleaner_snapshot=_snap(enabled=("a",)), capmd_version="0.1.0")
    k2 = compute_cache_key(pdf_bytes=pdf, page_range=None,
                          cleaner_snapshot=_snap(enabled=("b",)), capmd_version="0.1.0")
    k3 = compute_cache_key(pdf_bytes=pdf, page_range=None,
                          cleaner_snapshot=_snap(enabled=("a",), disabled=("b",)),
                          capmd_version="0.1.0")
    assert k1 != k2
    assert k1 != k3
    assert k2 != k3


def test_cache_key_changes_on_capmd_version() -> None:
    """capmd_version diferente → key diferente (invalida caches en upgrade)."""
    snap = _snap()
    k1 = compute_cache_key(pdf_bytes=b"a", page_range=None,
                          cleaner_snapshot=snap, capmd_version="0.1.0")
    k2 = compute_cache_key(pdf_bytes=b"a", page_range=None,
                          cleaner_snapshot=snap, capmd_version="0.2.0")
    assert k1 != k2


# ---------------------------------------------------------------------------
# compute_cleaner_config_snapshot
# ---------------------------------------------------------------------------


def test_snapshot_normalizes_order() -> None:
    """Snapshots con enabled en distinto orden → mismo JSON canónico."""
    s1 = compute_cleaner_config_snapshot(("a", "b", "c"), (), ())
    s2 = compute_cleaner_config_snapshot(("c", "a", "b"), (), ())
    assert s1.to_canonical_json() == s2.to_canonical_json()


def test_snapshot_distinguishes_enabled_vs_disabled() -> None:
    """enabled=["x"] vs disabled=["x"] → diferentes (mismo items, distinto efecto)."""
    s1 = compute_cleaner_config_snapshot(("x",), (), ())
    s2 = compute_cleaner_config_snapshot((), ("x",), ())
    assert s1.to_canonical_json() != s2.to_canonical_json()


# ---------------------------------------------------------------------------
# get_cache_dir
# ---------------------------------------------------------------------------


def test_cache_dir_uses_override_when_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`override` gana sobre env var y XDG."""
    monkeypatch.setenv("CAPMD_CACHE_DIR", str(tmp_path / "from-env"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    target = tmp_path / "from-override"
    resolved = get_cache_dir(override=str(target))
    assert resolved == target.resolve()


def test_cache_dir_uses_env_when_no_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`CAPMD_CACHE_DIR` gana sobre XDG si no hay override."""
    monkeypatch.setenv("CAPMD_CACHE_DIR", str(tmp_path / "from-env"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    resolved = get_cache_dir()
    assert resolved == (tmp_path / "from-env").resolve()


def test_cache_dir_uses_xdg_when_no_override_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin override ni env: usa $XDG_CACHE_HOME/capmd/convert/."""
    monkeypatch.delenv("CAPMD_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    resolved = get_cache_dir()
    assert resolved == (tmp_path / "xdg" / "capmd" / "convert")


def test_cache_dir_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin override/env/XDG → ~/.cache/capmd/convert/."""
    monkeypatch.delenv("CAPMD_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    resolved = get_cache_dir()
    assert resolved == (tmp_path / "home" / ".cache" / "capmd" / "convert")


def test_cache_dir_creates_missing_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el dir no existe, get_cache_dir lo crea."""
    target = tmp_path / "new" / "subdir"
    assert not target.exists()
    resolved = get_cache_dir(override=str(target))
    assert resolved == target.resolve()
    assert target.is_dir()


# ---------------------------------------------------------------------------
# save + load roundtrip
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Save + load devuelve un CacheEntry equivalente."""
    entry = save_cache_entry(
        tmp_path,
        key="abc123",
        markdown="# Title\n\nBody.",
        fm={"title": "Title", "book": "b"},
        capmd_version="0.1.0",
    )
    assert entry is not None
    loaded = load_cache_entry(tmp_path, "abc123")
    assert loaded is not None
    assert loaded.key == "abc123"
    assert loaded.version == BUNDLE_VERSION
    assert loaded.markdown == "# Title\n\nBody."
    assert loaded.fm == {"title": "Title", "book": "b"}
    assert loaded.images_meta == ()
    assert loaded.images_dir == ""


def test_load_returns_none_if_no_file(tmp_path: Path) -> None:
    """Cache dir vacío → load devuelve None."""
    assert load_cache_entry(tmp_path, "nonexistent") is None


def test_load_returns_none_on_corrupted_json(tmp_path: Path) -> None:
    """JSON inválido → None + warning."""
    target = tmp_path / "deadbeef.json"
    target.write_text("{not valid json", encoding="utf-8")
    assert load_cache_entry(tmp_path, "deadbeef") is None


def test_load_returns_none_on_schema_version_mismatch(
    tmp_path: Path,
) -> None:
    """Schema version diferente → None."""
    target = tmp_path / "abcd.json"
    target.write_text(
        '{"version": "2", "key": "abcd", "created_at": "2026-01-01T00:00:00Z", '
        '"capmd_version": "0.1.0", "markdown": "x", "fm": {}, '
        '"images_meta": [], "images_dir": ""}',
        encoding="utf-8",
    )
    assert load_cache_entry(tmp_path, "abcd") is None


def test_save_copies_images(tmp_path: Path) -> None:
    """Images se copian al sibling dir con su sha256."""
    img1 = tmp_path / "src1.png"
    img2 = tmp_path / "src2.jpg"
    img1.write_bytes(b"fake png content 1")
    img2.write_bytes(b"fake jpg content 2")

    entry = save_cache_entry(
        tmp_path,
        key="imgkey",
        markdown="# Body",
        fm={},
        images=(img1, img2),
        capmd_version="0.1.0",
    )
    assert entry is not None
    assert len(entry.images_meta) == 2

    images_dir = tmp_path / "imgkey__images"
    assert images_dir.is_dir()
    saved_files = {p.name for p in images_dir.iterdir()}
    # sha256("fake png content 1") + .png = <sha>.png
    assert any(f.endswith(".png") for f in saved_files)
    assert any(f.endswith(".jpg") for f in saved_files)


def test_save_handles_disk_full_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si write_text raisea OSError, save devuelve None y log warning."""
    from capmd import cache as cache_mod

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cache_mod, "_atomic_write_text", boom)
    entry = save_cache_entry(
        tmp_path,
        key="fail",
        markdown="x",
        fm={},
        capmd_version="0.1.0",
    )
    assert entry is None


def test_save_cache_entry_when_images_dir_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cuando ``images_dir.mkdir`` falla, entry se guarda SIN imágenes.

    Verifica el fallback: el bundle se persiste con ``images_meta=[]``
    en lugar de abortar la conversión. Sin esto, un cache dir read-only
    bloquearía silenciosamente la persistencia de conversiones sin
    imágenes (raro pero posible).
    """
    img1 = tmp_path / "src1.png"
    img1.write_bytes(b"fake png content")

    # Forzar OSError en mkdir del images dir (subdir del cache).
    from capmd import cache as cache_mod

    original_mkdir = cache_mod.Path.mkdir

    def failing_mkdir(self, *args: object, **kwargs: object) -> None:
        # Solo falla en el images dir (key__images), no en cache_dir.
        if self.name.endswith("__images"):
            raise OSError("read-only filesystem")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(cache_mod.Path, "mkdir", failing_mkdir)

    entry = save_cache_entry(
        tmp_path,
        key="noimgdir",
        markdown="# body",
        fm={},
        images=(img1,),
        capmd_version="0.1.0",
    )
    # Entry se guarda igual (sin imágenes).
    assert entry is not None
    assert entry.images_meta == ()  # sin imágenes
    assert entry.images_dir == ""  # flag vacío (no hay subdir)
    # El JSON bundle existe y es válido.
    import json

    bundle = json.loads((tmp_path / "noimgdir.json").read_text())
    assert bundle["images_meta"] == []
    assert bundle["images_dir"] == ""


# ---------------------------------------------------------------------------
# should_use_cache
# ---------------------------------------------------------------------------


def test_should_use_cache_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: True (cache activo)."""
    monkeypatch.delenv("CAPMD_NO_CACHE", raising=False)
    assert should_use_cache() is True


def test_should_use_cache_false_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`no_cache_flag=True` → False."""
    monkeypatch.delenv("CAPMD_NO_CACHE", raising=False)
    assert should_use_cache(no_cache_flag=True) is False


def test_should_use_cache_false_when_env_var_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CAPMD_NO_CACHE=1` → False (override del flag default)."""
    monkeypatch.setenv("CAPMD_NO_CACHE", "1")
    assert should_use_cache() is False


def test_should_use_cache_accepts_truthy_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CAPMD_NO_CACHE=true` o `yes` también desactivan el cache."""
    monkeypatch.delenv("CAPMD_NO_CACHE", raising=False)
    for value in ("true", "yes", "1", "TRUE"):
        monkeypatch.setenv("CAPMD_NO_CACHE", value)
        assert should_use_cache() is False, value


def test_should_use_cache_env_var_empty_does_not_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CAPMD_NO_CACHE=''` (string vacío) NO desactiva el cache."""
    monkeypatch.delenv("CAPMD_NO_CACHE", raising=False)
    monkeypatch.setenv("CAPMD_NO_CACHE", "")
    assert should_use_cache() is True
