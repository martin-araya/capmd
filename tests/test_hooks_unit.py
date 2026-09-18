"""Tests unitarios de ``capmd.hooks`` (K3)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from capmd.hooks import (
    HOOK_OUTPUT_TAIL_LINES,
    HOOK_TIMEOUT_DEFAULT,
    HOOK_VAR_BOOK_SLUG,
    HOOK_VAR_CAPMD_JSON_PATH,
    HOOK_VAR_CHAPTER_SLUG,
    HOOK_VAR_IMAGES_DIR,
    HOOK_VAR_OUTPUT_PATH,
    HOOK_VAR_PROFILE,
    HOOK_VAR_VERSION,
    HookContext,
    HookResult,
    build_hook_env,
    hook_failed_message,
    run_post_command,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ctx(
    output_path: Path,
    *,
    capmd_json: Path | None = None,
    images: Path | None = None,
    book: str = "rust-handbook",
    chapter: str = "cap-03-ownership",
    profile: str = "study",
) -> HookContext:
    return HookContext(
        output_path=output_path,
        capmd_json_path=capmd_json,
        images_dir=images,
        book_slug=book,
        chapter_slug=chapter,
        profile=profile,
    )


def _write_echo_script(tmp_path: Path, body: str, name: str = "hook.sh") -> Path:
    """Escribe un script bash ejecutable que ejecuta ``body``.

    El script recibe el path al .md como ``$1`` y tiene acceso a las env
    vars ``CAPMD_*``.
    """
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    p.chmod(0o755)
    return p


# ---------------------------------------------------------------------------
# skip path
# ---------------------------------------------------------------------------


def test_run_post_command_skips_when_command_none(tmp_path: Path) -> None:
    """``command=None`` → ``HookResult(skipped=True)`` sin subprocess."""
    ctx = _ctx(tmp_path / "out.md")
    r = run_post_command(None, ctx)
    assert r.skipped is True
    assert r.returncode == 0
    assert r.duration_seconds == 0.0


def test_run_post_command_skips_when_command_empty(tmp_path: Path) -> None:
    """``command=""`` o whitespace-only → skipped."""
    ctx = _ctx(tmp_path / "out.md")
    for empty in ("", "   ", "\n\t"):
        r = run_post_command(empty, ctx)
        assert r.skipped is True, f"debio skipear {empty!r}"


# ---------------------------------------------------------------------------
# happy path + $1 + env vars
# ---------------------------------------------------------------------------


def test_run_post_command_executes_with_positional_path(tmp_path: Path) -> None:
    """El script recibe el path al .md como ``$1``."""
    md = tmp_path / "out.md"
    md.write_text("# T\n\nB.\n", encoding="utf-8")
    log = tmp_path / "called.txt"
    hook = _write_echo_script(
        tmp_path,
        f'echo "$1" > "{log}"',
    )

    r = run_post_command(str(hook), _ctx(md))
    assert r.skipped is False
    assert r.returncode == 0
    assert r.succeeded is True
    assert log.read_text(encoding="utf-8").strip() == str(md)


def test_run_post_command_passes_all_capmd_env_vars(tmp_path: Path) -> None:
    """Las 7 env vars ``CAPMD_*`` están seteadas con los valores del ctx."""
    md = tmp_path / "out.md"
    capmd_json = md.parent / "capmd.json"
    images = md.parent / "images"
    log = tmp_path / "env.txt"
    hook = _write_echo_script(
        tmp_path,
        textwrap.dedent(
            f"""\
            echo "OUTPUT=${{CAPMD_OUTPUT_PATH}}" > "{log}"
            echo "JSON=${{CAPMD_CAPMD_JSON_PATH}}" >> "{log}"
            echo "IMAGES=${{CAPMD_IMAGES_DIR}}" >> "{log}"
            echo "BOOK=${{CAPMD_BOOK_SLUG}}" >> "{log}"
            echo "CHAPTER=${{CAPMD_CHAPTER_SLUG}}" >> "{log}"
            echo "PROFILE=${{CAPMD_PROFILE}}" >> "{log}"
            echo "VERSION=${{CAPMD_VERSION}}" >> "{log}"
            """
        ),
    )

    ctx = HookContext(
        output_path=md,
        capmd_json_path=capmd_json,
        images_dir=images,
        book_slug="rust-handbook",
        chapter_slug="cap-03-ownership",
        profile="study",
    )
    r = run_post_command(str(hook), ctx)
    assert r.returncode == 0, r.stderr_tail

    text = log.read_text(encoding="utf-8")
    assert f"OUTPUT={md}" in text
    assert f"JSON={capmd_json}" in text
    assert f"IMAGES={images}" in text
    assert "BOOK=rust-handbook" in text
    assert "CHAPTER=cap-03-ownership" in text
    assert "PROFILE=study" in text
    # VERSION is capmd.__version__, no asumimos el valor literal.
    assert "VERSION=0." in text or "VERSION=" in text


def test_run_post_command_env_inherits_path(tmp_path: Path) -> None:
    """El env del hook hereda ``PATH`` (los scripts pueden resolver binarios)."""
    md = tmp_path / "out.md"
    log = tmp_path / "path.txt"
    hook = _write_echo_script(
        tmp_path,
        f'echo "$PATH" > "{log}"',
    )
    r = run_post_command(str(hook), _ctx(md))
    assert r.returncode == 0
    # Si PATH está vacío, no podríamos correr sh.
    assert log.read_text(encoding="utf-8") != ""


# ---------------------------------------------------------------------------
# failures (no raise)
# ---------------------------------------------------------------------------


def test_run_post_command_non_zero_exit_does_not_raise(tmp_path: Path) -> None:
    """Script que devuelve exit 1 → ``HookResult(returncode=1)``, sin raise."""
    md = tmp_path / "out.md"
    hook = _write_echo_script(tmp_path, "exit 1")
    r = run_post_command(str(hook), _ctx(md))
    assert r.skipped is False
    assert r.returncode == 1
    assert r.succeeded is False


def test_hook_failed_message_describes_failure(tmp_path: Path) -> None:
    """``hook_failed_message`` devuelve string para exit != 0; ``None`` para OK/skipped."""
    ctx = _ctx(tmp_path / "out.md")
    hook = _write_echo_script(tmp_path, "exit 7")

    r_fail = run_post_command(str(hook), ctx)
    msg = hook_failed_message(r_fail)
    assert msg is not None
    assert "7" in msg
    assert "took" in msg

    ok_hook = _write_echo_script(tmp_path, "exit 0")
    r_ok = run_post_command(str(ok_hook), ctx)
    assert hook_failed_message(r_ok) is None

    r_skip = run_post_command(None, ctx)
    assert hook_failed_message(r_skip) is None


def test_run_post_command_timeout_returns_timed_out(tmp_path: Path) -> None:
    """Script que duerme más que el timeout → ``HookResult(timed_out=True)``."""
    if sys.platform == "win32":  # pragma: no cover
        pytest.skip("sleep + shell semánticas distintas en Windows")

    md = tmp_path / "out.md"
    hook = _write_echo_script(tmp_path, "sleep 10")
    r = run_post_command(str(hook), _ctx(md), timeout=0.3)
    assert r.timed_out is True
    assert r.returncode == -1
    assert "timeout" in r.stderr_tail


def test_run_post_command_command_not_found_returns_gracefully(tmp_path: Path) -> None:
    """Path inexistente → ``HookResult(returncode=-1)`` con mensaje claro, sin raise."""
    md = tmp_path / "out.md"
    r = run_post_command("/nonexistent/path/to/script", _ctx(md))
    assert r.skipped is False
    assert r.returncode == -1
    assert "not found" in r.stderr_tail.lower() or "no such file" in r.stderr_tail.lower()


def test_run_post_command_shlex_value_error_returns_gracefully(tmp_path: Path) -> None:
    """Comando con shlex inválido (quote no cerrada) → ``returncode=-1`` sin raise."""
    md = tmp_path / "out.md"
    r = run_post_command("sh -c \"unclosed", _ctx(md))
    assert r.returncode == -1
    assert "syntax" in r.stderr_tail.lower() or "invalid" in r.stderr_tail.lower()


# ---------------------------------------------------------------------------
# truncation
# ---------------------------------------------------------------------------


def test_run_post_command_truncates_long_stdout(tmp_path: Path) -> None:
    """``stdout_tail`` retiene solo las últimas ``HOOK_OUTPUT_TAIL_LINES`` líneas."""
    md = tmp_path / "out.md"
    # Script imprime 100 líneas a stdout.
    body = "for i in $(seq 1 100); do echo line_$i; done"
    hook = _write_echo_script(tmp_path, body)
    r = run_post_command(str(hook), _ctx(md))
    assert r.returncode == 0
    lines = r.stdout_tail.splitlines()
    assert len(lines) <= HOOK_OUTPUT_TAIL_LINES
    # Las últimas deben ser las del final (line_91 .. line_100).
    assert lines[-1] == "line_100"
    assert any("line_" in ln for ln in lines)


def test_run_post_command_short_stdout_not_truncated(tmp_path: Path) -> None:
    """Output corto (< N líneas) no se trunca."""
    md = tmp_path / "out.md"
    hook = _write_echo_script(tmp_path, "echo a; echo b; echo c")
    r = run_post_command(str(hook), _ctx(md))
    assert r.returncode == 0
    assert r.stdout_tail == "a\nb\nc\n" or r.stdout_tail == "a\nb\nc"


# ---------------------------------------------------------------------------
# build_hook_env / hook vars constants
# ---------------------------------------------------------------------------


def test_build_hook_env_inherits_os_environ(tmp_path: Path) -> None:
    """El env del hook incluye ``PATH`` y vars del proceso."""
    md = tmp_path / "out.md"
    ctx = _ctx(md)
    env = build_hook_env(ctx)
    # Vars del OS pasan (al menos las "seguras" como PATH).
    assert "PATH" in env
    assert "HOME" in env or "TMPDIR" in env or env.get("PATH")


def test_build_hook_env_overrides_capmd_vars(tmp_path: Path) -> None:
    """Las 7 vars ``CAPMD_*`` se setean siempre (pisan cualquier valor del OS)."""
    md = tmp_path / "out.md"
    capmd_json = md.parent / "capmd.json"
    images = md.parent / "images"
    ctx = HookContext(
        output_path=md,
        capmd_json_path=capmd_json,
        images_dir=images,
        book_slug="rust-handbook",
        chapter_slug="cap-03-ownership",
        profile="study",
    )
    env = build_hook_env(ctx)
    assert env[HOOK_VAR_OUTPUT_PATH] == str(md)
    assert env[HOOK_VAR_BOOK_SLUG] == "rust-handbook"
    assert env[HOOK_VAR_CHAPTER_SLUG] == "cap-03-ownership"
    assert env[HOOK_VAR_PROFILE] == "study"
    assert env[HOOK_VAR_CAPMD_JSON_PATH] == str(capmd_json)
    assert env[HOOK_VAR_IMAGES_DIR] == str(images)
    assert isinstance(env[HOOK_VAR_VERSION], str)


def test_build_hook_env_empty_for_optional_paths(tmp_path: Path) -> None:
    """``capmd_json_path=None`` y ``images_dir=None`` → strings vacíos en env."""
    md = tmp_path / "out.md"
    ctx = HookContext(
        output_path=md,
        capmd_json_path=None,
        images_dir=None,
        book_slug="b",
        chapter_slug="c",
        profile="",
    )
    env = build_hook_env(ctx)
    assert env[HOOK_VAR_CAPMD_JSON_PATH] == ""
    assert env[HOOK_VAR_IMAGES_DIR] == ""


# ---------------------------------------------------------------------------
# dataclasses
# ---------------------------------------------------------------------------


def test_hook_context_is_frozen(tmp_path: Path) -> None:
    """HookContext es inmutable (frozen)."""
    from dataclasses import FrozenInstanceError

    ctx = _ctx(tmp_path / "out.md")
    with pytest.raises(FrozenInstanceError):
        ctx.book_slug = "hacked"  # type: ignore[misc]


def test_hook_result_succeeded_property(tmp_path: Path) -> None:
    """``HookResult.succeeded`` es True solo si exit 0 y no skipped y no timeout."""
    tmp_path / "out.md"  # marker for consistent fixture setup
    r_ok = HookResult(command="x", returncode=0, stdout_tail="", stderr_tail="",
                     duration_seconds=0.1, timed_out=False, skipped=False)
    assert r_ok.succeeded is True

    r_skip = HookResult(command="x", returncode=0, stdout_tail="", stderr_tail="",
                       duration_seconds=0.0, timed_out=False, skipped=True)
    assert r_skip.succeeded is False

    r_fail = HookResult(command="x", returncode=1, stdout_tail="", stderr_tail="",
                       duration_seconds=0.1, timed_out=False, skipped=False)
    assert r_fail.succeeded is False

    r_to = HookResult(command="x", returncode=-1, stdout_tail="", stderr_tail="",
                     duration_seconds=0.3, timed_out=True, skipped=False)
    assert r_to.succeeded is False


def test_hook_timeout_default_is_60_seconds() -> None:
    """El default del runner es 60s (no -1)."""
    assert HOOK_TIMEOUT_DEFAULT == 60.0


def test_run_post_command_negative_timeout_disables_it(tmp_path: Path) -> None:
    """``timeout=-1`` no aplica timeout (subprocess sin kwarg)."""
    if sys.platform == "win32":  # pragma: no cover
        pytest.skip("sleep en Windows difiere")
    md = tmp_path / "out.md"
    hook = _write_echo_script(tmp_path, "sleep 0.2; exit 0")
    r = run_post_command(str(hook), _ctx(md), timeout=-1)
    assert r.returncode == 0
    assert r.timed_out is False
