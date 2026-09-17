"""Tests del watcher de carpeta + LaunchAgent (I3).

Cubre:
- :mod:`capmd.watch` — :func:`iter_events` (estabilidad), :func:`process_event`
  (conversión + move, dry-run, versioning), :func:`run_watch` (loop + SIGINT).
- :mod:`capmd.setup_launch_agent` — generación de plist XML, planning,
  rechazo off-macOS.
- CLI: ``capmd watch --help``, ``capmd setup launch-agent --help``,
  ``capmd setup launch-agent --dry-run``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from capmd.errors import CapmdError
from capmd.setup_launch_agent import (
    AGENT_LABEL,
    AGENT_PLIST_NAME,
    PlanResult,
    agent_plist_path,
    build_plist_xml,
    is_loaded,
    plan_install,
    plan_reinstall,
    plan_uninstall,
)
from capmd.watch import (
    WatchConfig,
    WatchEvent,
    iter_events,
    process_event,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _touch(path: Path, content: bytes = b"x", mtime: float | None = None) -> None:
    """Write ``content`` to ``path`` and optionally set mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class FakeSleep:
    """Reemplazo de ``time.sleep`` que solo registra lo pedido."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, secs: float) -> None:
        self.calls.append(secs)


# ---------------------------------------------------------------------------
# iter_events
# ---------------------------------------------------------------------------


def test_iter_events_emits_when_file_stabilises(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "book.pdf"
    _touch(target, b"hello")

    cfg = WatchConfig(
        inbox=inbox,
        out_dir=tmp_path / "out",
        move_to=tmp_path / "done",
        poll_interval_secs=0.0,
    )
    sleep = FakeSleep()
    seen: list[WatchEvent] = []
    gen = iter_events(cfg, sleep=sleep)
    stop = threading.Event()
    stop.clear()

    def driver() -> None:
        evt = next(gen)
        seen.append(evt)
        stop.set()

    t = threading.Thread(target=driver, daemon=True)
    t.start()
    t.join(timeout=2.0)
    assert seen, "iter_events nunca emitió"
    assert seen[0].path == target


def test_iter_events_does_not_emit_partial_writes(tmp_path: Path) -> None:
    """Un archivo que cambia entre dos polls no debe emitirse hasta que se estabilice."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "book.pdf"
    _touch(target, b"a")

    cfg = WatchConfig(
        inbox=inbox,
        out_dir=tmp_path / "out",
        move_to=tmp_path / "done",
        poll_interval_secs=0.0,
    )

    emitted: list[WatchEvent] = []
    stop = threading.Event()

    def runner() -> None:
        # Primer poll: aparece con size=1.  Cambiamos size a 10 antes del
        # segundo poll.  iter_events no debe emitir el primer estado.
        time.sleep(0.05)
        _touch(target, b"a" * 10)
        time.sleep(0.05)
        # Segundo poll (ahora mismo): cambia de tamaño → reset stability.
        # Esperamos un poco más y leemos el siguiente yield, que
        # corresponderá al estado estable.
        evt = next(gen)
        emitted.append(evt)
        stop.set()

    gen = iter_events(cfg, sleep=lambda s: None)
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=2.0)
    assert len(emitted) == 1
    assert emitted[0].path == target
    assert emitted[0].size == 10


def test_iter_events_filters_by_pattern(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _touch(inbox / "book.pdf")
    _touch(inbox / "image.png")
    _touch(inbox / "notes.txt")

    cfg = WatchConfig(
        inbox=inbox,
        out_dir=tmp_path / "out",
        move_to=tmp_path / "done",
        patterns=("*.pdf",),
        poll_interval_secs=0.0,
    )
    gen = iter_events(cfg, sleep=lambda s: None)
    evt = next(gen)
    assert evt.path.name == "book.pdf"


def test_iter_events_stops_on_stop_event(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    cfg = WatchConfig(
        inbox=inbox,
        out_dir=tmp_path / "out",
        move_to=tmp_path / "done",
        poll_interval_secs=0.0,
    )
    stop = threading.Event()
    stop.set()
    gen = iter_events(cfg, stop_event=stop)
    with pytest.raises(StopIteration):
        next(gen)


def test_iter_events_raises_if_inbox_missing(tmp_path: Path) -> None:
    cfg = WatchConfig(
        inbox=tmp_path / "missing",
        out_dir=tmp_path / "out",
        move_to=tmp_path / "done",
    )
    with pytest.raises(CapmdError) as exc_info:
        next(iter_events(cfg, sleep=lambda s: None))
    assert exc_info.value.exit_code == 7
    assert "inbox" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# process_event
# ---------------------------------------------------------------------------


def test_process_event_runs_conversion_then_moves(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = inbox / "book.pdf"
    _touch(src, b"%PDF-fake")
    out = tmp_path / "out"
    done = tmp_path / "done"

    cfg = WatchConfig(
        inbox=inbox,
        out_dir=out,
        move_to=done,
        poll_interval_secs=0.0,
    )
    captured: dict[str, Path] = {}

    def fake_runner(file: Path, output: Path) -> None:
        captured["file"] = file
        captured["out"] = output

    event = WatchEvent(src, src.stat().st_mtime, src.stat().st_size)
    ok = process_event(event, cfg, runner=fake_runner)
    assert ok is True
    assert captured["file"] == src
    assert captured["out"] == out
    assert (done / "book.pdf").exists()
    assert not src.exists(), "el original debería haberse movido"


def test_process_event_returns_false_on_runner_failure(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = inbox / "bad.pdf"
    _touch(src)
    cfg = WatchConfig(
        inbox=inbox,
        out_dir=tmp_path / "out",
        move_to=tmp_path / "done",
    )

    def failing(file: Path, output: Path) -> None:
        raise RuntimeError("convert failed")

    event = WatchEvent(src, src.stat().st_mtime, src.stat().st_size)
    ok = process_event(event, cfg, runner=failing)
    assert ok is False
    assert src.exists(), "el original debe quedar en el inbox si falla la conversión"


def test_process_event_dry_run_does_nothing(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = inbox / "book.pdf"
    _touch(src)
    cfg = WatchConfig(
        inbox=inbox,
        out_dir=tmp_path / "out",
        move_to=tmp_path / "done",
        dry_run=True,
    )
    calls: list[tuple[Path, Path]] = []

    def spy_runner(file: Path, output: Path) -> None:
        calls.append((file, output))

    event = WatchEvent(src, src.stat().st_mtime, src.stat().st_size)
    ok = process_event(event, cfg, runner=spy_runner)
    assert ok is True
    assert calls == [], "dry-run no debe invocar el runner"
    assert src.exists(), "dry-run no debe mover el archivo"


def test_process_event_versions_on_collision(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = inbox / "book.pdf"
    _touch(src)
    done = tmp_path / "done"
    done.mkdir()
    (done / "book.pdf").write_bytes(b"already there")

    cfg = WatchConfig(
        inbox=inbox,
        out_dir=tmp_path / "out",
        move_to=done,
    )

    event = WatchEvent(src, src.stat().st_mtime, src.stat().st_size)
    ok = process_event(event, cfg, runner=lambda f, o: None)
    assert ok is True
    assert (done / "book-1.pdf").exists()
    assert not src.exists()


# ---------------------------------------------------------------------------
# setup_launch_agent
# ---------------------------------------------------------------------------


def test_agent_plist_path_under_library() -> None:
    p = agent_plist_path()
    assert p.name == AGENT_PLIST_NAME
    assert "LaunchAgents" in str(p)


def test_build_plist_xml_is_valid_plist() -> None:
    import plistlib

    xml = build_plist_xml(
        capmd_path=Path("/usr/local/bin/capmd"),
        inbox=Path("/Users/test/Inbox"),
        out_dir=Path("/Users/test/Estudio"),
        move_to=Path("/Users/test/Processed"),
    )
    data = plistlib.loads(xml)
    assert data["Label"] == AGENT_LABEL
    assert data["ProgramArguments"][0] == "/usr/local/bin/capmd"
    assert data["ProgramArguments"][1] == "watch"
    assert "--inbox" in data["ProgramArguments"]
    assert "--out" in data["ProgramArguments"]
    assert "--move-to" in data["ProgramArguments"]
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] == {"Crashed": True}
    assert "StandardOutPath" in data
    assert "StandardErrorPath" in data


def test_plan_install_emits_launchctl_load() -> None:
    plan = plan_install(
        inbox=Path("/Users/test/Inbox"),
        out_dir=Path("/Users/test/Estudio"),
        move_to=Path("/Users/test/Processed"),
    )
    assert isinstance(plan, PlanResult)
    assert any("launchctl" in label for label, _ in plan.commands)
    assert any("load" in argv for _, argv in plan.commands)


def test_plan_uninstall_emits_launchctl_unload() -> None:
    plan = plan_uninstall()
    assert any(
        "unload" in argv for _, argv in plan.commands
    )


def test_plan_reinstall_is_install_plus_uninstall() -> None:
    plan = plan_reinstall(
        inbox=Path("/Users/test/Inbox"),
        out_dir=Path("/Users/test/Estudio"),
        move_to=Path("/Users/test/Processed"),
    )
    cmds = plan.commands
    assert any("unload" in argv for _, argv in cmds)
    assert any("load" in argv for _, argv in cmds)


def test_plan_install_refuses_off_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    with pytest.raises(CapmdError) as exc_info:
        plan_install(
            inbox=Path("/tmp/x"),
            out_dir=Path("/tmp/y"),
            move_to=Path("/tmp/z"),
        )
    assert exc_info.value.exit_code == 2
    assert "macOS" in str(exc_info.value)


def test_is_loaded_refuses_off_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    with pytest.raises(CapmdError):
        is_loaded()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _capmd_bin() -> Path:
    from shutil import which

    p = which("capmd")
    if not p:
        pytest.skip("capmd no está en PATH; corré `uv pip install -e .`")
    return Path(p)


def test_watch_help() -> None:
    bin_path = _capmd_bin()
    proc = subprocess.run(
        [str(bin_path), "watch", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 0
    out = proc.stdout
    for flag in ("--inbox", "--out", "--move-to", "--debounce", "--poll-interval", "--dry-run"):
        assert flag in out, f"{flag} no aparece en `capmd watch --help`"


def test_setup_launch_agent_help() -> None:
    bin_path = _capmd_bin()
    proc = subprocess.run(
        [str(bin_path), "setup", "launch-agent", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 0
    out = proc.stdout
    for flag in ("--inbox", "--out", "--move-to", "--install", "--uninstall", "--reinstall", "--dry-run", "--print-cmd"):
        assert flag in out


def test_setup_launch_agent_dry_run_does_not_touch_filesystem(
    tmp_path: Path,
) -> None:
    bin_path = _capmd_bin()
    inbox = tmp_path / "inbox"
    out = tmp_path / "out"
    done = tmp_path / "done"
    for p in (inbox, out, done):
        p.mkdir()
    proc = subprocess.run(
        [
            str(bin_path),
            "setup",
            "launch-agent",
            "--dry-run",
            "--inbox",
            str(inbox),
            "--out",
            str(out),
            "--move-to",
            str(done),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    out_text = proc.stdout
    assert "launchctl" in out_text
    assert "load" in out_text


def test_setup_launch_agent_print_cmd_shows_plan(tmp_path: Path) -> None:
    bin_path = _capmd_bin()
    inbox = tmp_path / "inbox"
    out = tmp_path / "out"
    done = tmp_path / "done"
    for p in (inbox, out, done):
        p.mkdir()
    proc = subprocess.run(
        [
            str(bin_path),
            "setup",
            "launch-agent",
            "--print-cmd",
            "--inbox",
            str(inbox),
            "--out",
            str(out),
            "--move-to",
            str(done),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    assert "launchctl" in proc.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="sólo aplica off-macOS")
def test_setup_launch_agent_refuses_on_linux(tmp_path: Path) -> None:
    """Sanity check: en cualquier OS que no sea macOS el comando falla con exit 2."""
    if sys.platform == "darwin":
        pytest.skip()
    # No llegamos acá en CI: el marker skipif nos excluye.
