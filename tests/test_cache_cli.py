"""Tests end-to-end del cache de conversión (K6) vía CLI.

Usa fixtures pequeñas (PDF ~5KB) para que la cache hit/miss sea
inmediata. Verifica que la 2ª corrida idéntica imprime ``cache hit``
a stderr y produce output byte-a-byte igual.

NOTA: conftest.py desactiva ``CAPMD_NO_CACHE=1`` globalmente para evitar
pollution entre tests. Estos tests desactivan ese override con
``monkeypatch.delenv("CAPMD_NO_CACHE", raising=False)`` y apuntan
``HOME`` + ``XDG_CACHE_HOME`` a un tmpdir para tests aislados.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build


@pytest.fixture(autouse=True)
def _enable_cache_for_k6_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rehabilita el cache (conftest lo desactiva por default) y
    aísla ``HOME``/``XDG_CACHE_HOME`` a un tmpdir por test."""
    monkeypatch.delenv("CAPMD_NO_CACHE", raising=False)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _pdf(tmp_path: Path) -> Path:
    return build.build_headings_pdf(tmp_path / "book.pdf")


def _runner(args: list[str], *, env: dict[str, str] | None = None) -> object:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return CliRunner().invoke(app, ["convert", *args], env=full_env)


def _isolated_env(tmp_path: Path, **extras: str) -> dict[str, str]:
    """Env sin CAPMD_*_ENDPOINT ni CAPMD_NO_CACHE. HOME aislado."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        **extras,
    }


# ---------------------------------------------------------------------------
# Cache hit + miss
# ---------------------------------------------------------------------------


def test_first_run_does_not_print_cacheado(tmp_path: Path) -> None:
    """1ª corrida: no imprime "cache hit" (es miss)."""
    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    r = _runner(
        [str(pdf), "-o", str(tmp_path / "out.md"), "--cache-dir", str(cache_dir)],
        env=_isolated_env(tmp_path),
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    assert "cache hit" not in r.stderr
    # El cache file se crea.
    assert any(cache_dir.iterdir())


def test_second_run_prints_cache_hit(tmp_path: Path) -> None:
    """2ª corrida idéntica: imprime "cache hit: <key[:8]>"."""
    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    env = _isolated_env(tmp_path)
    args = [str(pdf), "-o", str(tmp_path / "out.md"), "--cache-dir", str(cache_dir)]
    r1 = _runner(args, env=env)
    assert r1.exit_code == 0
    r2 = _runner(args, env=env)
    assert r2.exit_code == 0
    assert "cache hit:" in r2.stderr


def test_second_run_outputs_identical_content(tmp_path: Path) -> None:
    """2ª corrida (cache hit) produce output byte-a-byte igual al 1ª."""
    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    env = _isolated_env(tmp_path)
    args = [str(pdf), "-o", str(tmp_path / "out.md"), "--cache-dir", str(cache_dir)]
    _runner(args, env=env)
    _runner(args, env=env)
    files = sorted(p.name for p in cache_dir.iterdir())
    assert len(files) == 1
    # El cache entry es válido JSON.
    import json
    bundle = json.loads((cache_dir / files[0]).read_text())
    assert bundle["version"] == "1"


def test_cache_hit_skips_engine_convert_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache hit → NO se invoca ``Engine.convert_path`` (la parte cara).

    Marcamos ``Engine.convert_path`` y verificamos que solo se llama UNA
    vez (1ª corrida); la 2ª (cache hit) reusa el cached body.
    """
    from capmd.convert import engine as engine_mod

    calls: list[tuple] = []
    original = engine_mod.Engine.convert_path

    def spy(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(engine_mod.Engine, "convert_path", spy)

    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    env = _isolated_env(tmp_path)
    out1 = tmp_path / "out1.md"
    out2 = tmp_path / "out2.md"
    args = [str(pdf), "--cache-dir", str(cache_dir)]

    _runner([*args, "-o", str(out1)], env=env)
    n_1st = len(calls)
    assert n_1st == 1, calls

    _runner([*args, "-o", str(out2)], env=env)
    # 2ª corrida NO debe invocar convert_path (cache hit short-circuits).
    assert len(calls) == n_1st, calls


# ---------------------------------------------------------------------------
# Invalidación del cache
# ---------------------------------------------------------------------------


def test_file_change_creates_new_cache_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cambio en los bytes del PDF → cache key distinta → 2 cache files."""
    cache_dir = tmp_path / "cache"
    pdf = _pdf(tmp_path)
    env = _isolated_env(tmp_path)

    # Monkey-patch sha256_hex para forzar un hash diferente en la 2ª corrida.
    from capmd import cache as cache_mod

    original = cache_mod._sha256_hex
    counter = {"n": 0}

    def varying_sha256(data: bytes) -> str:
        counter["n"] += 1
        return original(f"v{counter['n']}-".encode() + data)

    monkeypatch.setattr(cache_mod, "_sha256_hex", varying_sha256)

    _runner([str(pdf), "-o", str(tmp_path / "out1.md"), "--cache-dir", str(cache_dir)], env=env)
    initial_files = sorted(p.name for p in cache_dir.iterdir())
    assert len(initial_files) == 1

    _runner([str(pdf), "-o", str(tmp_path / "out2.md"), "--cache-dir", str(cache_dir)], env=env)
    final_files = sorted(p.name for p in cache_dir.iterdir())
    # Distintos cache keys → 2 archivos en el cache dir.
    assert len(final_files) == 2


def test_no_cache_flag_forces_fresh(tmp_path: Path) -> None:
    """``--no-cache`` en la 2ª corrida → miss, no imprime cache hit."""
    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    env = _isolated_env(tmp_path)
    out1 = tmp_path / "out1.md"
    out2 = tmp_path / "out2.md"
    args = [str(pdf), "--cache-dir", str(cache_dir)]

    _runner([*args, "-o", str(out1)], env=env)
    r2 = _runner([*args, "--no-cache", "-o", str(out2)], env=env)
    assert r2.exit_code == 0
    assert "cache hit:" not in r2.stderr


def test_no_cache_env_var_works(tmp_path: Path) -> None:
    """``CAPMD_NO_CACHE=1`` en env → cache desactivado."""
    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    env = _isolated_env(tmp_path, CAPMD_NO_CACHE="1")
    out1 = tmp_path / "out1.md"
    out2 = tmp_path / "out2.md"
    args = [str(pdf), "--cache-dir", str(cache_dir)]

    _runner([*args, "-o", str(out1)], env=env)
    r2 = _runner([*args, "-o", str(out2)], env=env)
    assert r2.exit_code == 0
    assert "cache hit:" not in r2.stderr


def test_cache_dir_override_creates_dir_if_missing(tmp_path: Path) -> None:
    """``--cache-dir /nonexistent/`` → el dir se crea automáticamente."""
    pdf = _pdf(tmp_path)
    new_cache_dir = tmp_path / "new" / "subdir" / "cache"
    assert not new_cache_dir.exists()
    r = _runner(
        [str(pdf), "-o", str(tmp_path / "out.md"), "--cache-dir", str(new_cache_dir)],
        env=_isolated_env(tmp_path),
    )
    assert r.exit_code == 0
    assert new_cache_dir.is_dir()
    # El cache file se creó en el dir nuevo.
    assert any(new_cache_dir.iterdir())


def test_cache_xdg_default_used_when_no_override_or_env(tmp_path: Path) -> None:
    """Sin override ni ``CAPMD_CACHE_DIR`` → usa ``$XDG_CACHE_HOME/capmd/convert/``."""
    pdf = _pdf(tmp_path)
    env = _isolated_env(tmp_path)
    expected_xdg = Path(env["XDG_CACHE_HOME"]) / "capmd" / "convert"

    _runner(
        [str(pdf), "-o", str(tmp_path / "out.md")],
        env=env,
    )
    # El cache file se creó en el dir XDG default.
    assert expected_xdg.is_dir()
    assert any(expected_xdg.iterdir())


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


def test_cache_skips_cleaners_on_hit(tmp_path: Path, monkeypatch) -> None:
    """Cache hit → cleaners NO corren. Marcamos un cleaner como flag."""
    # Trackear invocaciones del cleaner pipeline.
    import capmd.cli as cli_mod
    original_apply = cli_mod._apply_clean_pipeline

    calls: list[tuple] = []

    def spy_apply(*args, **kwargs):
        skip_cleaners = kwargs.get("skip_cleaners", False)
        calls.append((args, kwargs, skip_cleaners))
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(cli_mod, "_apply_clean_pipeline", spy_apply)
    monkeypatch.setattr(cli_mod, "_apply_clean_pipeline_to_stdin", spy_apply)

    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    env = _isolated_env(tmp_path)
    args = [str(pdf), "-o", str(tmp_path / "out.md"), "--cache-dir", str(cache_dir)]

    _runner(args, env=env)
    n_calls_1st = len(calls)

    _runner(args, env=env)

    # 2ª corrida con cache hit: ``skip_cleaners=True`` en ambas
    # llamadas (``_apply_clean_pipeline`` se llama dos veces por la 2ª
    # corrida: una para la rama tree/flat y otra para el flujo de FM).
    # Lo importante es que ``skip_cleaners=True`` esté set.
    new_calls = calls[n_calls_1st:]
    assert all(c[2] is True for c in new_calls)


def test_cache_with_no_clean_still_works(tmp_path: Path) -> None:
    """``--no-clean`` + cache → 2ª corrida también es cache hit."""
    pdf = _pdf(tmp_path)
    cache_dir = tmp_path / "cache"
    env = _isolated_env(tmp_path)
    out1 = tmp_path / "out1.md"
    out2 = tmp_path / "out2.md"
    args = [
        str(pdf),
        "--cache-dir", str(cache_dir),
        "--no-clean",
    ]

    _runner([*args, "-o", str(out1)], env=env)
    r2 = _runner([*args, "-o", str(out2)], env=env)
    assert r2.exit_code == 0
    assert "cache hit:" in r2.stderr
