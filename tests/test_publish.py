"""Tests for scripts/publish.sh (J4).

Mockeamos `uv` (no asumimos red) y verificamos que el script:
- Valida version contra pyproject.toml.
- Rechaza `--to` invalido.
- Falla si faltan artefactos en dist/.
- Falla sin `UV_PUBLISH_TOKEN` (excepto `--dry-run`).
- Construye el publish-url correcto por target.
- Con `--dry-run` NO invoca `uv publish`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISH_SCRIPT = REPO_ROOT / "scripts" / "publish.sh"


def _run_publish(
    tmp_path: Path,
    *,
    args: list[str],
    with_fake_uv: bool = True,
    uv_records: Path | None = None,
    env_extra: dict[str, str] | None = None,
    pyproject_text: str | None = None,
    dist_files: tuple[str, ...] = ("capmd-0.2.0.tar.gz", "capmd-0.2.0-py3-none-any.whl"),
) -> subprocess.CompletedProcess[str]:
    """Run scripts/publish.sh inside ``tmp_path`` after seeding artefacts."""
    if pyproject_text is None:
        shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    else:
        (tmp_path / "pyproject.toml").write_text(pyproject_text)

    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    for name in dist_files:
        (dist / name).write_bytes(b"fake artifact")

    env = {**os.environ}
    if with_fake_uv:
        fake = tmp_path / "_bin"
        fake.mkdir(exist_ok=True)
        # Fake uv que NO sube nada; solo registra invocaciones en ``uv_records``.
        if uv_records is not None:
            (fake / "uv").write_text(
                "#!/usr/bin/env sh\n"
                'for a in "$@"; do echo "uv: $a" >> "$UV_RECORDS"; done\n'
                'echo "$UV_PUBLISH_TOKEN" >> "$UV_RECORDS"\n'
                'exit 0\n'
            )
            env["UV_RECORDS"] = str(uv_records)
        else:
            (fake / "uv").write_text(
                "#!/usr/bin/env sh\n"
                'echo "uv called: $@" >&2\n'
                "exit 0\n"
            )
        (fake / "uv").chmod(0o755)
        env["PATH"] = str(fake) + ":" + env.get("PATH", "")

    if env_extra:
        env.update(env_extra)

    return subprocess.run(
        ["bash", str(PUBLISH_SCRIPT), *args, str(tmp_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_publish_rejects_unknown_target(tmp_path: Path) -> None:
    proc = _run_bump_equivalent(tmp_path, args=["0.2.0", "--to", "bogus"])
    assert proc.returncode != 0
    assert "--to debe ser testpypi o pypi" in proc.stderr


def _run_bump_equivalent(tmp_path: Path, **kwargs) -> subprocess.CompletedProcess[str]:
    """Wrapper que asegura pyproject con v0.2.0 para que no falle la validacion de version."""
    if "pyproject_text" not in kwargs:
        kwargs["pyproject_text"] = '[project]\nname = "capmd"\nversion = "0.2.0"\n'
    return _run_publish(tmp_path, **kwargs)


def test_publish_validates_version(tmp_path: Path) -> None:
    proc = _run_bump_equivalent(tmp_path, args=["9.9.9", "--dry-run"])
    assert proc.returncode != 0
    assert "pyproject.toml version '0.2.0' != '9.9.9'" in proc.stderr


def test_publish_requires_artifacts(tmp_path: Path) -> None:
    proc = _run_bump_equivalent(
        tmp_path,
        args=["0.2.0", "--dry-run"],
        dist_files=(),  # sin artefactos
    )
    assert proc.returncode != 0
    assert "artefactos faltan" in proc.stderr


def test_publish_requires_token(tmp_path: Path) -> None:
    proc = _run_bump_equivalent(tmp_path, args=["0.2.0", "--to", "pypi"], env_extra={})
    # sin UV_PUBLISH_TOKEN y sin --dry-run → aborta.
    os.environ.pop("UV_PUBLISH_TOKEN", None)
    proc = _run_bump_equivalent(tmp_path, args=["0.2.0", "--to", "pypi"])
    assert proc.returncode != 0
    assert "UV_PUBLISH_TOKEN" in proc.stderr


def test_publish_dry_run_skips_upload(tmp_path: Path) -> None:
    records = tmp_path / "uv_calls.log"
    proc = _run_bump_equivalent(
        tmp_path,
        args=["0.2.0", "--to", "pypi", "--dry-run"],
        uv_records=records,
    )
    assert proc.returncode == 0
    assert not records.exists(), "dry-run no debe invocar uv"
    assert "DRY RUN" in proc.stdout


def test_publish_testpypi_url(tmp_path: Path) -> None:
    records = tmp_path / "uv_calls.log"
    proc = _run_bump_equivalent(
        tmp_path,
        args=["0.2.0", "--to", "testpypi"],
        uv_records=records,
        env_extra={"UV_PUBLISH_TOKEN": "pypi-test"},
    )
    assert proc.returncode == 0, proc.stderr
    log = records.read_text()
    assert "test.pypi.org" in log
    assert "pypi-test" in log


def test_publish_pypi_url(tmp_path: Path) -> None:
    records = tmp_path / "uv_calls.log"
    proc = _run_bump_equivalent(
        tmp_path,
        args=["0.2.0", "--to", "pypi"],
        uv_records=records,
        env_extra={"UV_PUBLISH_TOKEN": "pypi-real"},
    )
    assert proc.returncode == 0, proc.stderr
    log = records.read_text()
    assert "upload.pypi.org" in log
    assert "pypi-real" in log
