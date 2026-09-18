"""Tests end-to-end del hook ``post_command`` (K3) via CLI."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from capmd.cli import app
from tests.fixtures import build

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _outline_pdf(tmp_path: Path) -> Path:
    return build.build_outline_toc_pdf(tmp_path / "Rust Handbook.pdf")


def _runner_convert(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> object:
    """Inyecta ``env`` sobre el proceso; cambia a ``cwd`` (via os.chdir
    dentro de un try/finally) para que ``./capmd.toml`` resuelva al
    tmpdir del test.

    Nota: CliRunner no acepta ``cwd=``; usamos ``os.chdir`` + restore.
    """
    import os

    full_env = dict(os.environ)
    if env:
        full_env.update(env)

    old_cwd = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        return CliRunner().invoke(app, ["convert", *args], env=full_env)
    finally:
        os.chdir(old_cwd)


def _write_hook_script(tmp_path: Path, body: str, name: str = "hook.sh") -> Path:
    """Escribe un script bash ejecutable que ejecuta ``body``.

    El script recibe el path al .md como ``$1`` y tiene acceso a las env
    vars ``CAPMD_*``.
    """
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def _setup_capmd_toml(
    tmp_path: Path, *, post_command_body: str = 'echo "$1" > "{log}"'
) -> Path:
    """Escribe un ``capmd.toml`` con ``[hooks].post_command`` que escribe
    ``$1`` al tmpfile ``log.txt``. Devuelve el path al log."""
    log = tmp_path / "log.txt"
    body = post_command_body.format(log=log)
    hook = _write_hook_script(
        tmp_path,
        body,
        name="hook.sh",
    )
    cfg_path = tmp_path / "capmd.toml"
    cfg_path.write_text(
        f'[hooks]\npost_command = "{hook}"\n', encoding="utf-8"
    )
    return log


def _invocation_env(tmp_path: Path) -> dict[str, str]:
    """Env para el subprocess de Typer: HOME global capado al tmp_path."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}


# ---------------------------------------------------------------------------
# Happy path: hook fires after successful write
# ---------------------------------------------------------------------------


def test_cli_post_command_runs_after_successful_write(tmp_path: Path) -> None:
    """``--config-file capmd.toml`` con ``post_command`` → hook fires una vez,
    el script recibe el path al .md como ``$1``."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    log = _setup_capmd_toml(tmp_path)
    result = _runner_convert(
        [str(pdf), "-o", str(out)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert out.is_file()
    assert log.is_file(), "el hook no se invocó"
    # El log contiene la ruta absoluta al .md.
    assert log.read_text(encoding="utf-8").strip() == str(out.resolve())


def test_cli_post_command_passes_all_env_vars(tmp_path: Path) -> None:
    """El script puede leer todas las env vars ``CAPMD_*`` del contexto."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    log = tmp_path / "env.txt"
    hook = _write_hook_script(
        tmp_path,
        dedent(
            f"""\
            echo "OUTPUT=${{CAPMD_OUTPUT_PATH}}" > "{log}"
            echo "BOOK=${{CAPMD_BOOK_SLUG}}" >> "{log}"
            echo "CHAPTER=${{CAPMD_CHAPTER_SLUG}}" >> "{log}"
            echo "PROFILE=${{CAPMD_PROFILE}}" >> "{log}"
            echo "VERSION=${{CAPMD_VERSION}}" >> "{log}"
            """
        ),
    )
    cfg = tmp_path / "capmd.toml"
    cfg.write_text(f'[hooks]\npost_command = "{hook}"\n', encoding="utf-8")

    result = _runner_convert(
        [str(pdf), "-o", str(out)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    text = log.read_text(encoding="utf-8")
    assert f"OUTPUT={out.resolve()}" in text
    assert "BOOK=" in text
    assert "CHAPTER=" in text
    assert "PROFILE=" in text  # vacío cuando no se usó --profile
    assert "VERSION=0." in text


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_cli_post_command_failure_does_not_fail_capmd(tmp_path: Path) -> None:
    """Hook que devuelve exit != 0 → capmd sigue exit 0, warning visible."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    hook = _write_hook_script(tmp_path, "echo 'hook failed' >&2; exit 7")
    cfg = tmp_path / "capmd.toml"
    cfg.write_text(f'[hooks]\npost_command = "{hook}"\n', encoding="utf-8")

    result = _runner_convert(
        [str(pdf), "-o", str(out)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    # capmd exit 0 a pesar del fallo del hook.
    assert result.exit_code == 0, (result.stdout, result.stderr)
    # El .md sí se escribió.
    assert out.is_file()
    # Warning visible en stderr.
    assert "hook" in result.stderr.lower()
    assert "7" in result.stderr


def test_cli_post_command_command_not_found_does_not_fail(tmp_path: Path) -> None:
    """Path al hook inexistente → capmd exit 0, warning visible, .md escrito."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    cfg = tmp_path / "capmd.toml"
    cfg.write_text(
        '[hooks]\npost_command = "/nonexistent/path/to/script"\n',
        encoding="utf-8",
    )

    result = _runner_convert(
        [str(pdf), "-o", str(out)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert out.is_file()
    assert "not found" in result.stderr.lower() or "no such" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def test_cli_post_command_not_invoked_on_stdout(tmp_path: Path) -> None:
    """Sin ``-o`` ni ``--out``, no hay path a pasar → hook NO se invoca."""
    pdf = _outline_pdf(tmp_path)
    log = _setup_capmd_toml(tmp_path)
    result = _runner_convert(
        [str(pdf)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert not log.exists(), f"hook se invocó en stdout: log={log}"


def test_cli_post_command_not_invoked_on_dry_run(tmp_path: Path) -> None:
    """``--dry-run`` → plan-only, hook NO se invoca."""
    pdf = _outline_pdf(tmp_path)
    log = _setup_capmd_toml(tmp_path)
    result = _runner_convert(
        [str(pdf), "--dry-run"],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0
    assert not log.exists(), "hook se invocó en --dry-run"


def test_cli_no_post_command_no_invocation(tmp_path: Path) -> None:
    """Sin TOML con ``[hooks]`` → no se invoca nada."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    cfg = tmp_path / "capmd.toml"  # existe pero sin [hooks]
    cfg.write_text("# empty\n", encoding="utf-8")
    log = tmp_path / "log.txt"

    # Si el hook se invocara, escribiría algo acá. No lo hace.
    result = _runner_convert(
        [str(pdf), "-o", str(out)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0
    assert out.is_file()
    assert not log.exists()


# ---------------------------------------------------------------------------
# Fire count
# ---------------------------------------------------------------------------


def test_cli_post_command_with_split_h2_fires_once(tmp_path: Path) -> None:
    """Con ``--split h2``, el hook se invoca UNA sola vez (root .md)."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "estudio"
    log = _setup_capmd_toml(tmp_path)
    result = _runner_convert(
        [
            str(pdf),
            "--split", "h2",
            "--out", str(out_dir),
        ],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert log.is_file()
    # El log debe tener UNA sola línea (un solo fire).
    content = log.read_text(encoding="utf-8")
    assert content.count("\n") <= 1, f"hook fired multiple times:\n{content}"


# ---------------------------------------------------------------------------
# Tree mode env vars (CAPMD_CAPMD_JSON_PATH, CAPMD_IMAGES_DIR)
# ---------------------------------------------------------------------------


def test_cli_post_command_in_tree_mode_passes_json_and_images_paths(
    tmp_path: Path,
) -> None:
    """Tree mode: env vars ``CAPMD_CAPMD_JSON_PATH`` y ``CAPMD_IMAGES_DIR``
    apuntan a los paths correctos."""
    pdf = _outline_pdf(tmp_path)
    out_dir = tmp_path / "estudio"
    log = tmp_path / "env.txt"
    hook = _write_hook_script(
        tmp_path,
        dedent(
            f"""\
            echo "JSON=${{CAPMD_CAPMD_JSON_PATH}}" > "{log}"
            echo "IMAGES=${{CAPMD_IMAGES_DIR}}" >> "{log}"
            echo "OUTPUT=${{CAPMD_OUTPUT_PATH}}" >> "{log}"
            """
        ),
    )
    cfg = tmp_path / "capmd.toml"
    cfg.write_text(f'[hooks]\npost_command = "{hook}"\n', encoding="utf-8")

    result = _runner_convert(
        [str(pdf), "--out", str(out_dir)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    text = log.read_text(encoding="utf-8")
    # JSON path apunta a un archivo que existe.
    assert "JSON=" in text
    assert "IMAGES=" in text
    assert "OUTPUT=" in text
    # El JSON path debe terminar en capmd.json.
    assert "capmd.json" in text
    # El images dir debe terminar en /images.
    assert "/images\n" in text


# ---------------------------------------------------------------------------
# Book profile override
# ---------------------------------------------------------------------------


def test_cli_post_command_book_profile_overrides_global(tmp_path: Path) -> None:
    """``[books.<id>].post_command`` gana sobre ``[hooks].post_command``."""
    # Setup: hook global + hook por libro.
    pdf = _outline_pdf(tmp_path)
    global_log = tmp_path / "global.log"
    book_log = tmp_path / "book.log"
    global_hook = _write_hook_script(
        tmp_path, f'echo GLOBAL > "{global_log}"', name="global.sh"
    )
    book_hook = _write_hook_script(
        tmp_path, f'echo BOOK > "{book_log}"', name="book.sh"
    )

    cfg = tmp_path / "capmd.toml"
    cfg.write_text(
        dedent(
            f"""\
            [hooks]
            post_command = "{global_hook}"

            [books."rust-handbook"]
            post_command = "{book_hook}"
            """
        ),
        encoding="utf-8",
    )

    result = _runner_convert(
        [str(pdf), "-o", str(tmp_path / "out.md"), "--book", "rust-handbook"],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    # El book hook se invocó, el global NO.
    assert book_log.is_file(), "book hook no se invocó"
    assert "BOOK" in book_log.read_text(encoding="utf-8")
    assert not global_log.exists(), "global hook se invocó (debio ser override)"


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_cli_post_command_timeout_configurable(tmp_path: Path) -> None:
    """``post_command_timeout`` en TOML mata al hook si supera el límite."""
    pdf = _outline_pdf(tmp_path)
    out = tmp_path / "out.md"
    # Hook que duerme 5s; timeout de 0.3s.
    hook = _write_hook_script(tmp_path, "sleep 5")
    cfg = tmp_path / "capmd.toml"
    cfg.write_text(
        dedent(
            f"""\
            [hooks]
            post_command = "{hook}"
            post_command_timeout = 0.3
            """
        ),
        encoding="utf-8",
    )

    result = _runner_convert(
        [str(pdf), "-o", str(out)],
        env=_invocation_env(tmp_path), cwd=tmp_path,
    )
    # capmd termina exit 0; el .md se escribió.
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert out.is_file()
    # Warning de timeout visible en stderr.
    assert "timeout" in result.stderr.lower() or "timed out" in result.stderr.lower()
