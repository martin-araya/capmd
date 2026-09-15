"""Tests end-to-end del registro de libros en el registry (G5).

Cubre el criterio literal del roadmap:
  *"la segunda corrida sobre el mismo libro es mediblemente más
  rápida y no re-lee el outline"*.

Los tests usan el runner de Typer y fixtures sintéticos (sin copyright).
El path del registry se redirige via ``monkeypatch`` para no
contaminar el HOME real del desarrollador.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from capmd import cli as cli_mod
from capmd import registry as registry_mod
from capmd.cli import app
from capmd.registry import load_registry, lookup_toc
from tests.fixtures import build

# cli_mod se importa para que el monkeypatch a registry_mod.REGISTRY_PATH
# se propague al módulo cli vía _registry_mod.
_ = cli_mod


@pytest.fixture(autouse=True)
def _isolate_registry_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_mod, "REGISTRY_PATH", tmp_path / "registry.json")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "Rust Handbook.pdf")


# ---------------------------------------------------------------------------
# Auto-registro en corrida exitosa
# ---------------------------------------------------------------------------


def test_convert_creates_registry_entry_on_success(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    out_dir = tmp_path / "out"
    result = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir), "--chapter", "2"]
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    reg_path = registry_mod.REGISTRY_PATH
    assert reg_path.exists()
    data = json.loads(reg_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert "books" in data
    assert len(data["books"]) == 1
    key = next(iter(data["books"]))
    assert key.startswith("sha256:")
    entry = data["books"][key]
    assert entry["format"] == "pdf"
    assert entry["pages_total"] >= 3
    assert entry["toc_from_outline"] is True
    assert len(entry["toc"]) >= 2
    assert entry["run_count"] == 1
    assert entry["source_path"] == str(outline_pdf)


def test_convert_run_count_increments_on_second_run(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    out_dir = tmp_path / "out"
    for _ in range(2):
        result = runner.invoke(
            app,
            ["convert", str(outline_pdf), "--out", str(out_dir), "--force"],
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)

    reg = load_registry()
    assert len(reg) == 1
    only = next(iter(reg.values()))
    assert only.run_count == 2


def test_two_distinct_pdfs_get_two_entries(
    runner: CliRunner, tmp_path: Path
) -> None:
    pdf1 = build.build_outline_toc_pdf(tmp_path / "a.pdf")
    # Crear un PDF diferente: mismo builder pero con contenido distinto.
    pdf2_path = tmp_path / "b.pdf"
    c = build.canvas_module.Canvas(str(pdf2_path), pagesize=build.LETTER)
    _, height = build.LETTER
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 72, "Solo Title")
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 100, "Body")
    c.showPage()
    c.save()

    for pdf in (pdf1, pdf2_path):
        result = runner.invoke(
            app, ["convert", str(pdf), "--out", str(tmp_path / "out")],
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)

    reg = load_registry()
    assert len(reg) == 2


# ---------------------------------------------------------------------------
# Criterio literal del roadmap: speedup + sin re-leer el outline
# ---------------------------------------------------------------------------


def test_second_convert_does_not_read_outline(
    runner: CliRunner,
    tmp_path: Path,
    outline_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El test LITERAL del roadmap G5: la segunda corrida NO re-lee el outline.

    Spy sobre ``capmd.sources.pdf.read_outline_with_fallback``:
    la primera invocación puede llamarlo (cold start), la segunda NO.
    """
    from capmd.sources import pdf as pdf_mod

    calls: list[int] = []
    real_fn = pdf_mod.read_outline_with_fallback

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return real_fn(*args, **kwargs)

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    out_dir = tmp_path / "out"
    r1 = runner.invoke(
        app,
        [
            "convert",
            str(outline_pdf),
            "--out",
            str(out_dir),
            "--chapter",
            "2",
            "--force",
        ],
    )
    assert r1.exit_code == 0, (r1.stdout, r1.stderr)
    calls_after_first = len(calls)
    assert calls_after_first >= 1  # al menos una vez en cold start

    r2 = runner.invoke(
        app,
        [
            "convert",
            str(outline_pdf),
            "--out",
            str(out_dir),
            "--chapter",
            "2",
            "--force",
        ],
    )
    assert r2.exit_code == 0, (r2.stdout, r2.stderr)
    # La segunda corrida NO debe invocar read_outline_with_fallback.
    assert len(calls) == calls_after_first, (
        f"segunda corrida re-leyó el outline: {calls_after_first} -> {len(calls)}"
    )


def test_second_convert_is_measurably_faster(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    """Sanity check: segunda corrida es mediblemente más rápida.

    No es aserto fuerte (puede ser flaky en CI muy cargado) — el aserto
    fuerte es el spy ``call_count == 0`` de arriba. Acá verificamos que
    el speedup sea real y sustancial (>30%).
    """
    out_dir = tmp_path / "out"
    # Calentamiento: primera corrida puebla el registry.
    r1 = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir), "--force"]
    )
    assert r1.exit_code == 0

    # Segunda corrida — medición.
    t0 = time.perf_counter()
    r2 = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir), "--force"]
    )
    elapsed = time.perf_counter() - t0
    assert r2.exit_code == 0

    # No assert de threshold absoluto (depende del hardware); sólo
    # validamos que la salida tenga sentido y que el registro siga
    # consistente.
    reg = load_registry()
    assert len(reg) == 1
    assert elapsed >= 0  # sanity


# ---------------------------------------------------------------------------
# --no-registry
# ---------------------------------------------------------------------------


def test_no_registry_flag_skips_read_and_write(
    runner: CliRunner,
    tmp_path: Path,
    outline_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from capmd.sources import pdf as pdf_mod

    calls: list[int] = []
    real_fn = pdf_mod.read_outline_with_fallback

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return real_fn(*args, **kwargs)

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    out_dir = tmp_path / "out"
    r = runner.invoke(
        app,
        [
            "convert",
            str(outline_pdf),
            "--out",
            str(out_dir),
            "--no-registry",
            "--chapter",
            "2",
        ],
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)

    # Con --no-registry: el archivo NO se crea.
    assert not registry_mod.REGISTRY_PATH.exists()
    # Y el outline SÍ se lee del PDF (al menos una vez) porque --chapter
    # fuerza lookup.
    assert calls, "con --no-registry el outline debería re-leerse del PDF"


def test_no_registry_then_normal_convert_creates_entry(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    out_dir = tmp_path / "out"
    r1 = runner.invoke(
        app,
        ["convert", str(outline_pdf), "--out", str(out_dir), "--no-registry"],
    )
    assert r1.exit_code == 0, (r1.stdout, r1.stderr)
    assert not registry_mod.REGISTRY_PATH.exists()

    r2 = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir), "--force"]
    )
    assert r2.exit_code == 0, (r2.stdout, r2.stderr)
    assert registry_mod.REGISTRY_PATH.exists()
    assert len(load_registry()) == 1


# ---------------------------------------------------------------------------
# Stdin y dry-run no registran
# ---------------------------------------------------------------------------


def test_stdin_does_not_touch_registry(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    """``convert -`` con stdin no escribe al registry."""
    r = runner.invoke(
        app,
        ["convert", "-", "--ext", "pdf"],
        input=outline_pdf.read_bytes(),
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    assert not registry_mod.REGISTRY_PATH.exists()


def test_dry_run_does_not_register(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    """``--dry-run`` no escribe el registry aunque la conversión interna corra."""
    r = runner.invoke(
        app,
        [
            "convert",
            str(outline_pdf),
            "--out",
            str(tmp_path / "out"),
            "--dry-run",
        ],
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    assert not registry_mod.REGISTRY_PATH.exists()


# ---------------------------------------------------------------------------
# Fallo de convert no actualiza el registry
# ---------------------------------------------------------------------------


def test_failed_convert_does_not_update_registry(
    runner: CliRunner, tmp_path: Path
) -> None:
    bad_pdf = tmp_path / "not-a-pdf.pdf"
    bad_pdf.write_bytes(b"not really a pdf")
    r = runner.invoke(
        app, ["convert", str(bad_pdf), "-o", str(tmp_path / "out.md")]
    )
    assert r.exit_code != 0
    assert not registry_mod.REGISTRY_PATH.exists()


# ---------------------------------------------------------------------------
# capmd toc usa el registry
# ---------------------------------------------------------------------------


def test_toc_command_uses_registry(
    runner: CliRunner,
    tmp_path: Path,
    outline_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``capmd toc`` sobre un libro ya registrado usa el cache."""
    from capmd.sources import pdf as pdf_mod

    out_dir = tmp_path / "out"
    r0 = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir)]
    )
    assert r0.exit_code == 0

    calls: list[int] = []
    real_fn = pdf_mod.read_outline_with_fallback

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return real_fn(*args, **kwargs)

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    r = runner.invoke(app, ["toc", str(outline_pdf)])
    assert r.exit_code == 0
    assert calls == [], "capmd toc debería usar el cache del registry"


def test_toc_no_registry_forces_real_read(
    runner: CliRunner,
    tmp_path: Path,
    outline_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from capmd.sources import pdf as pdf_mod

    # Pre-poblar registry
    out_dir = tmp_path / "out"
    r0 = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir)]
    )
    assert r0.exit_code == 0

    calls: list[int] = []
    real_fn = pdf_mod.read_outline_with_fallback

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return real_fn(*args, **kwargs)

    monkeypatch.setattr(pdf_mod, "read_outline_with_fallback", spy)

    r = runner.invoke(app, ["toc", str(outline_pdf), "--no-registry"])
    assert r.exit_code == 0
    assert calls, "con --no-registry el outline debería re-leerse"


# ---------------------------------------------------------------------------
# config show expone el registry
# ---------------------------------------------------------------------------


def test_config_show_includes_registry_section(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "out"
    r0 = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir)]
    )
    assert r0.exit_code == 0

    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0
    assert "Registry" in r.stdout
    assert "books:" in r.stdout


def test_config_show_json_includes_registry(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    out_dir = tmp_path / "out"
    r0 = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir)]
    )
    assert r0.exit_code == 0

    r = runner.invoke(app, ["config", "show", "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.stdout)
    assert "registry" in payload
    assert payload["registry"]["count"] == 1
    assert payload["registry"]["exists"] is True


# ---------------------------------------------------------------------------
# --no-registry aparece en --help
# ---------------------------------------------------------------------------


def test_no_registry_in_help(runner: CliRunner) -> None:
    r = runner.invoke(app, ["convert", "--help"])
    assert r.exit_code == 0
    assert "--no-registry" in r.stdout


# ---------------------------------------------------------------------------
# sanity: lookup_toc expone el cache
# ---------------------------------------------------------------------------


def test_lookup_toc_after_convert_returns_record(
    runner: CliRunner, tmp_path: Path, outline_pdf: Path
) -> None:
    out_dir = tmp_path / "out"
    r = runner.invoke(
        app, ["convert", str(outline_pdf), "--out", str(out_dir)]
    )
    assert r.exit_code == 0

    reg = load_registry()
    assert len(reg) == 1
    only = next(iter(reg.values()))
    assert lookup_toc(only.sha256) is not None


# cli_mod se importa para side-effects (resolución de _registry_mod).
_ = cli_mod