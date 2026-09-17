"""J1 coverage gap tests: cierran los huecos grandes del reporte de
``coverage``. Cada clase apunta a un módulo específico. Los tests usan
``monkeypatch`` y mocks para alcanzar branches que de otro modo requieren
macOS, SDKs externos, o fixtures costosas.

Las clases NO duplican tests existentes en ``test_<module>.py``: solo
ejercitan branches que el reporte marca como no cubiertos.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# macOS-only modules: simular sys.platform = "darwin" para que las funciones
# crean los planes/paths y podamos inspeccionar el resultado.
# ---------------------------------------------------------------------------


@pytest.fixture
def macos_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")


@pytest.fixture
def non_macos_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")


class TestSetupLaunchAgentMacOS:
    def test_plan_install_emits_launchctl_load(
        self, macos_platform: None, tmp_path: Path
    ) -> None:
        from capmd.setup_launch_agent import plan_install

        plan = plan_install(
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        assert plan.files_to_create
        assert any("load" in cmd[1][1] for cmd in plan.commands)
        assert any("RunAtLoad" in n or "KeepAlive" in n or "Logs" in n for n in plan.notes)

    def test_plan_uninstall(self, macos_platform: None, tmp_path: Path) -> None:
        from capmd.setup_launch_agent import plan_uninstall

        plan = plan_uninstall()
        assert plan.files_to_remove
        assert any("unload" in cmd[1][1] for cmd in plan.commands)

    def test_plan_reinstall_combines(self, macos_platform: None, tmp_path: Path) -> None:
        from capmd.setup_launch_agent import plan_reinstall

        plan = plan_reinstall(
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        # uninstall + install → at least one unload + one load command.
        labels = [c[0] for c in plan.commands]
        assert labels.count("launchctl") >= 2

    def test_plan_install_off_macos_raises(
        self, non_macos_platform: None, tmp_path: Path
    ) -> None:
        from capmd.setup_launch_agent import LaunchAgentNotSupportedError, plan_install

        with pytest.raises(LaunchAgentNotSupportedError):
            plan_install(
                inbox=tmp_path / "inbox",
                out_dir=tmp_path / "out",
                move_to=tmp_path / "done",
            )

    def test_build_plist_xml_validates(self, macos_platform: None, tmp_path: Path) -> None:
        import plistlib

        from capmd.setup_launch_agent import build_plist_xml

        xml = build_plist_xml(
            capmd_path=Path("/usr/local/bin/capmd"),
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        data = plistlib.loads(xml)
        assert data["Label"] == "com.martinaraya.capmd-watch"
        assert data["RunAtLoad"] is True
        assert data["KeepAlive"]["Crashed"] is True

    def test_build_plist_xml_escapes_paths(self, macos_platform: None, tmp_path: Path) -> None:
        from capmd.setup_launch_agent import build_plist_xml

        # Path con espacios → verificar que el XML es parseable.
        xml = build_plist_xml(
            capmd_path=Path("/usr/local/bin/capmd"),
            inbox=Path("/path with spaces/inbox"),
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        import plistlib

        data = plistlib.loads(xml)
        assert "ProgramArguments" in data

    def test_resolve_capmd_binary_override_exists(self, macos_platform: None, tmp_path: Path) -> None:
        from capmd.setup_launch_agent import _resolve_capmd_binary

        fake_bin = tmp_path / "capmd"
        fake_bin.write_text("#!/bin/sh\n")
        result = _resolve_capmd_binary(override=fake_bin)
        assert result == fake_bin

    def test_resolve_capmd_binary_override_missing_raises(self, macos_platform: None) -> None:
        from capmd.setup_launch_agent import LaunchAgentNotSupportedError, _resolve_capmd_binary

        with pytest.raises(LaunchAgentNotSupportedError):
            _resolve_capmd_binary(override=Path("/nonexistent/capmd"))

    def test_resolve_capmd_binary_not_in_path_raises(self, macos_platform: None) -> None:
        from capmd.setup_launch_agent import LaunchAgentNotSupportedError, _resolve_capmd_binary

        # capmd might or might not be in PATH; force "not found" via monkeypatch.
        with (
            patch("capmd.setup_launch_agent.shutil.which", return_value=None),
            pytest.raises(LaunchAgentNotSupportedError),
        ):
            _resolve_capmd_binary()

    def test_agent_plist_path(self) -> None:
        from capmd.setup_launch_agent import agent_plist_path

        p = agent_plist_path()
        assert p.name == "com.martinaraya.capmd-watch.plist"
        assert "LaunchAgents" in str(p)

    def test_plan_summary_lines(self, macos_platform: None, tmp_path: Path) -> None:
        from capmd.setup_launch_agent import plan_install

        plan = plan_install(
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        lines = plan.summary_lines()
        assert any("create file" in ln for ln in lines)
        assert any("launchctl" in ln for ln in lines)
        assert any("note:" in ln for ln in lines)

    def test_execute_plan_launchctl_load_failure(
        self, macos_platform: None, tmp_path: Path
    ) -> None:
        from capmd.setup_launch_agent import (
            LaunchAgentNotSupportedError,
            _execute_plan,
            plan_install,
        )

        plan = plan_install(
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        # Make load fail with nonzero rc.
        with patch("capmd.setup_launch_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="boom", stdout="")
            with pytest.raises(LaunchAgentNotSupportedError, match="falló"):
                _execute_plan(plan)

    def test_execute_plan_launchctl_unload_failure_ignored(
        self, macos_platform: None, tmp_path: Path
    ) -> None:
        from capmd.setup_launch_agent import _execute_plan, plan_uninstall

        plan = plan_uninstall()
        with patch("capmd.setup_launch_agent.subprocess.run") as mock_run:
            # unload failure is OK (idempotent).
            mock_run.return_value = MagicMock(returncode=1, stderr="", stdout="")
            # Should not raise.
            _execute_plan(plan)

    def test_is_loaded_returns_false_when_launchctl_fails(self, macos_platform: None) -> None:
        from capmd.setup_launch_agent import is_loaded

        with patch("capmd.setup_launch_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert is_loaded() is False

    def test_is_loaded_returns_true_when_ok(self, macos_platform: None) -> None:
        from capmd.setup_launch_agent import is_loaded

        with patch("capmd.setup_launch_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert is_loaded() is True


class TestSetupQuickActionMacOS:
    def test_plan_install(self, macos_platform: None, tmp_path: Path) -> None:
        from capmd.setup_quickaction import plan_install

        plan = plan_install(shortcut_path=tmp_path / "fake.shortcut")
        assert any(cmd[0] == "open" for cmd in plan.commands)
        assert plan.notes

    def test_plan_uninstall(self, macos_platform: None) -> None:
        from capmd.setup_quickaction import plan_uninstall

        plan = plan_uninstall()
        assert any("osascript" in cmd[1][0] for cmd in plan.commands)

    def test_plan_install_off_macos_raises(
        self, non_macos_platform: None, tmp_path: Path
    ) -> None:
        from capmd.setup_quickaction import QuickActionNotSupportedError, plan_install

        with pytest.raises(QuickActionNotSupportedError):
            plan_install(shortcut_path=tmp_path / "fake.shortcut")

    def test_plan_uninstall_off_macos_raises(self, non_macos_platform: None) -> None:
        from capmd.setup_quickaction import QuickActionNotSupportedError, plan_uninstall

        with pytest.raises(QuickActionNotSupportedError):
            plan_uninstall()

    def test_resolve_shortcut_path_override(self, tmp_path: Path) -> None:
        from capmd.setup_quickaction import resolve_shortcut_path

        override = tmp_path / "my.shortcut"
        override.write_bytes(b"x")
        assert resolve_shortcut_path(override=override) == override

    def test_uninstall_applescript_failure_raises(self, macos_platform: None) -> None:
        from capmd.setup_quickaction import QuickActionNotSupportedError, uninstall

        with patch("capmd.setup_quickaction.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stderr="real failure", stdout="")
            with pytest.raises(QuickActionNotSupportedError, match="failed to delete"):
                uninstall()

    def test_uninstall_applescript_not_found_is_ok(self, macos_platform: None) -> None:
        from capmd.setup_quickaction import uninstall

        with patch("capmd.setup_quickaction.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="not found", stdout="")
            # rc=1 → "not found" → idempotent, no raise.
            uninstall()

    def test_install_shortcut_failure_raises(self, macos_platform: None, tmp_path: Path) -> None:
        from capmd.setup_quickaction import QuickActionNotSupportedError, install

        with patch("capmd.setup_quickaction.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="open failed", stdout="")
            with pytest.raises(QuickActionNotSupportedError, match="exited"):
                install(shortcut_path=tmp_path / "fake.shortcut")


class TestWatchMacOS:
    def test_run_watch_inbox_missing_raises(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, WatchError, run_watch

        cfg = WatchConfig(
            inbox=tmp_path / "missing",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        with pytest.raises(WatchError, match="inbox no existe"):
            run_watch(cfg, install_signal_handlers=False)

    def test_run_watch_inbox_is_file_raises(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, WatchError, run_watch

        fake_inbox = tmp_path / "not-a-dir"
        fake_inbox.write_text("x")
        cfg = WatchConfig(
            inbox=fake_inbox,
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        with pytest.raises(WatchError, match="no es un directorio"):
            run_watch(cfg, install_signal_handlers=False)

    def test_default_runner_capmd_not_in_path(self, tmp_path: Path) -> None:
        from capmd.watch import WatchError, _default_runner

        with (
            patch("capmd.watch.shutil.which", return_value=None),
            pytest.raises(WatchError, match="capmd no encontrado"),
        ):
            _default_runner(tmp_path / "x.pdf", tmp_path / "out")

    def test_default_runner_subprocess_called(self, tmp_path: Path) -> None:
        from capmd.watch import _default_runner

        with (
            patch("capmd.watch.shutil.which", return_value="/usr/bin/capmd"),
            patch("capmd.watch.subprocess.run") as mock_run,
        ):
            _default_runner(tmp_path / "x.pdf", tmp_path / "out")
            args = mock_run.call_args.args[0]
            assert args[0] == "/usr/bin/capmd"
            assert "--quiet" in args
            assert "convert" in args

    def test_process_event_dry_run(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, WatchEvent, process_event

        cfg = WatchConfig(
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
            dry_run=True,
        )
        event = WatchEvent(path=tmp_path / "x.pdf", mtime=0.0, size=10)
        assert process_event(event, cfg) is True
        # runner no debería haberse llamado.
        assert not (tmp_path / "out").exists()
        assert not (tmp_path / "done").exists()

    def test_process_event_runner_failure_returns_false(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, WatchEvent, process_event

        cfg = WatchConfig(
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )

        def bad_runner(p: Path, o: Path) -> None:
            raise RuntimeError("boom")

        event = WatchEvent(path=tmp_path / "x.pdf", mtime=0.0, size=10)
        (tmp_path / "x.pdf").write_bytes(b"x")
        assert process_event(event, cfg, runner=bad_runner) is False

    def test_process_event_versions_on_collision(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, WatchEvent, process_event

        cfg = WatchConfig(
            inbox=tmp_path / "inbox",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        # Pre-create the destination with the same name.
        done = tmp_path / "done"
        done.mkdir()
        (done / "x.pdf").write_bytes(b"old")

        def ok_runner(p: Path, o: Path) -> None:
            pass

        event = WatchEvent(path=tmp_path / "x.pdf", mtime=0.0, size=10)
        (tmp_path / "x.pdf").write_bytes(b"x")
        assert process_event(event, cfg, runner=ok_runner) is True
        # Versioned file exists.
        assert (done / "x-1.pdf").exists()

    def test_watchconfig_path_coercion(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig

        cfg = WatchConfig(
            inbox=str(tmp_path / "inbox"),
            out_dir=str(tmp_path / "out"),
            move_to=str(tmp_path / "done"),
        )
        assert isinstance(cfg.inbox, Path)
        assert isinstance(cfg.out_dir, Path)
        assert isinstance(cfg.move_to, Path)

    def test_iter_events_scan_raises_filenotfound(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, WatchError, _scan_candidates

        cfg = WatchConfig(
            inbox=tmp_path / "missing",
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
        )
        with pytest.raises(WatchError, match="inbox no existe"):
            list(_scan_candidates(cfg.inbox, cfg.patterns))

    def test_iter_events_not_a_directory(self, tmp_path: Path) -> None:
        from capmd.watch import WatchError, _scan_candidates

        not_dir = tmp_path / "not-a-dir"
        not_dir.write_text("x")
        with pytest.raises(WatchError, match="no es un directorio"):
            list(_scan_candidates(not_dir, ("*.pdf",)))

    def test_iter_events_file_disappeared_between_scan_and_stat(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, iter_events

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        # Don't create any file; iter_events should just keep polling.
        cfg = WatchConfig(
            inbox=inbox,
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
            poll_interval_secs=0.01,
        )
        stop = threading.Event()
        stop.set()  # stop immediately
        # Should return without crashing.
        list(iter_events(cfg, stop_event=stop, sleep=lambda _s: None))

    def test_run_watch_signal_handlers_install(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, run_watch

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        cfg = WatchConfig(
            inbox=inbox,
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
            poll_interval_secs=0.0,
        )

        # Patch run_watch to not actually loop.
        with (
            patch("capmd.watch.iter_events", return_value=iter([])),
            patch("capmd.watch.signal.signal") as mock_signal,
        ):
            run_watch(cfg, runner=lambda f, o: None, install_signal_handlers=True)
            assert mock_signal.call_count >= 1

    def test_run_watch_dry_run_log(self, tmp_path: Path) -> None:
        from capmd.watch import WatchConfig, run_watch

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        cfg = WatchConfig(
            inbox=inbox,
            out_dir=tmp_path / "out",
            move_to=tmp_path / "done",
            poll_interval_secs=0.0,
            dry_run=True,
        )
        with patch("capmd.watch.iter_events", return_value=iter([])):
            run_watch(cfg, install_signal_handlers=False)

    def test_next_versioned_path_helper(self, tmp_path: Path) -> None:
        from capmd.watch import _next_versioned_path

        target = tmp_path / "book.pdf"
        target.write_bytes(b"x")
        versioned = _next_versioned_path(target)
        assert versioned.name == "book-1.pdf"

        # Pre-create book-1 too → expect book-2.
        (tmp_path / "book-1.pdf").write_bytes(b"x")
        versioned = _next_versioned_path(target)
        assert versioned.name == "book-2.pdf"

    def test_next_versioned_path_too_many_collisions(self, tmp_path: Path) -> None:
        from capmd.watch import WatchError, _next_versioned_path

        target = tmp_path / "x.pdf"
        target.write_bytes(b"x")
        for n in range(1, 10000):
            (tmp_path / f"x-{n}.pdf").write_bytes(b"x")
        with pytest.raises(WatchError, match="demasiadas colisiones"):
            _next_versioned_path(target)


# ---------------------------------------------------------------------------
# llm.py
# ---------------------------------------------------------------------------


class TestLLMGaps:
    def test_default_models_has_all_providers(self) -> None:
        from capmd.llm import DEFAULT_MODELS

        for provider in ("openai", "anthropic", "google"):
            assert provider in DEFAULT_MODELS
            assert DEFAULT_MODELS[provider]

    def test_env_keys_in_priority_order(self) -> None:
        from capmd.llm import ENV_KEYS

        assert ENV_KEYS == ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")

    def test_detect_provider_no_env_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        from capmd.llm import detect_provider_from_env

        assert detect_provider_from_env() is None

    def test_build_llm_client_default_model_openai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``model=None`` debe usar el default del proveedor."""
        from capmd import llm

        class FakeOpenAI:
            def __init__(self) -> None:
                pass

        fake_module = MagicMock()
        fake_module.OpenAI = FakeOpenAI
        monkeypatch.setitem(sys.modules, "openai", fake_module)

        result = llm.build_llm_client("openai")  # model=None → default
        assert isinstance(result, FakeOpenAI)

    def test_build_llm_client_anthropic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from capmd import llm

        class FakeAnthropic:
            def __init__(self) -> None:
                pass

        fake_module = MagicMock()
        fake_module.Anthropic = FakeAnthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)

        result = llm.build_llm_client("anthropic", model="claude-3")
        assert isinstance(result, FakeAnthropic)

    def test_build_llm_client_google(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from capmd import llm

        class FakeClient:
            def __init__(self) -> None:
                pass

        fake_google = MagicMock()
        fake_genai = MagicMock()
        fake_genai.Client = FakeClient
        fake_google.genai = fake_genai
        monkeypatch.setitem(sys.modules, "google", fake_google)
        monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

        result = llm.build_llm_client("google", model="gemini-2")
        assert isinstance(result, FakeClient)

    def test_build_llm_client_anthropic_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        from capmd import llm

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "anthropic":
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match="anthropic SDK requerido"):
            llm.build_llm_client("anthropic")

    def test_build_llm_client_google_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        from capmd import llm

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "google":
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match="google-genai SDK requerido"):
            llm.build_llm_client("google")

    def test_build_llm_client_default_model_unknown_provider(self) -> None:
        from capmd.llm import build_llm_client

        # Unknown provider with model=None → ValueError.
        with pytest.raises(ValueError, match="proveedor LLM desconocido"):
            build_llm_client("bogus", model=None)


# ---------------------------------------------------------------------------
# registry.py
# ---------------------------------------------------------------------------


class TestRegistryGaps:
    def _write_registry(self, tmp_path: Path, data: dict[str, Any]) -> Path:
        reg = tmp_path / "registry.json"
        reg.write_text(json.dumps(data))
        return reg

    def test_load_root_not_dict(self, tmp_path: Path) -> None:
        from capmd.registry import load_registry

        reg = self._write_registry(tmp_path, [])
        assert load_registry(reg) == {}

    def test_load_books_not_dict(self, tmp_path: Path) -> None:
        from capmd.registry import load_registry

        reg = self._write_registry(tmp_path, {"books": []})
        assert load_registry(reg) == {}

    def test_load_skip_invalid_entry(self, tmp_path: Path) -> None:
        from capmd.registry import load_registry

        reg = self._write_registry(
            tmp_path,
            {
                "books": {
                    "sha256:" + "a" * 64: {
                        "sha256": "a" * 64,
                        "title": "t",
                        "format": "pdf",
                        "pages_total": 1,
                        "toc": [],
                        "toc_from_outline": False,
                        "source_path": "/x.pdf",
                        "registered_at": "2026-01-01T00:00:00Z",
                        "last_seen_at": "2026-01-01T00:00:00Z",
                        "run_count": 1,
                    },
                    "broken": "not a dict",
                }
            },
        )
        loaded = load_registry(reg)
        assert "sha256:" + "a" * 64 in loaded
        assert "broken" not in loaded

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        from capmd.registry import save_registry

        target = tmp_path / "nested" / "deeper" / "reg.json"
        save_registry({}, target)
        assert target.exists()

    def test_save_atomic_uses_replace(self, tmp_path: Path) -> None:
        from capmd.registry import save_registry

        target = tmp_path / "reg.json"
        with patch("capmd.registry.os.replace") as mock_replace:
            save_registry({}, target)
            mock_replace.assert_called()

    def test_upsert_new(self, tmp_path: Path) -> None:
        from capmd.registry import BookRecord, load_registry, upsert_book

        rec = BookRecord(
            sha256="a" * 64,
            title="t",
            format="pdf",
            pages_total=1,
            toc=(),
            toc_from_outline=False,
            source_path="/x.pdf",
            registered_at="2026-01-01T00:00:00Z",
            last_seen_at="2026-01-01T00:00:00Z",
            run_count=1,
        )
        path = tmp_path / "reg.json"
        upsert_book(rec, path=path)
        loaded = load_registry(path)
        assert loaded["sha256:" + "a" * 64].run_count == 1

    def test_upsert_existing_bumps_count(self, tmp_path: Path) -> None:
        from capmd.registry import BookRecord, load_registry, upsert_book

        rec1 = BookRecord(
            sha256="a" * 64,
            title="t",
            format="pdf",
            pages_total=1,
            toc=(),
            toc_from_outline=False,
            source_path="/x.pdf",
            registered_at="2026-01-01T00:00:00Z",
            last_seen_at="2026-01-01T00:00:00Z",
            run_count=1,
        )
        rec2 = BookRecord(
            sha256="a" * 64,
            title="t",
            format="pdf",
            pages_total=1,
            toc=(),
            toc_from_outline=False,
            source_path="/x.pdf",
            registered_at="2026-01-01T00:00:00Z",
            last_seen_at="2026-01-02T00:00:00Z",
            run_count=1,
        )
        path = tmp_path / "reg.json"
        upsert_book(rec1, path=path)
        upsert_book(rec2, path=path)
        loaded = load_registry(path)
        assert loaded["sha256:" + "a" * 64].run_count == 2
        assert loaded["sha256:" + "a" * 64].registered_at == "2026-01-01T00:00:00Z"

    def test_lookup_toc_miss(self, tmp_path: Path) -> None:
        from capmd.registry import lookup_toc

        assert lookup_toc("missing") is None

    def test_lookup_toc_short_sha_returns_none(self) -> None:
        from capmd.registry import lookup_toc

        # Short sha → None (lookup_toc is non-raising).
        assert lookup_toc("abc") is None

    def test_make_record_helper(self, tmp_path: Path) -> None:
        from capmd.registry import make_record

        rec = make_record(
            sha256_hex="a" * 64,
            title="t",
            format="pdf",
            pages_total=1,
            toc=(),
            source_path=tmp_path / "x.pdf",
            toc_from_outline=False,
        )
        assert rec.sha256 == "a" * 64
        assert rec.run_count == 1


# ---------------------------------------------------------------------------
# cli_render.py
# ---------------------------------------------------------------------------


class TestCliRenderGaps:
    def test_render_outline_tree(self, tmp_path: Path) -> None:
        from capmd.cli_render import render_outline_tree
        from capmd.models import Chapter

        chapters = [
            Chapter(title="Intro", level=1, start_page=1, end_page=2, index=1),
            Chapter(title="Section", level=2, start_page=3, end_page=5, index=2),
        ]
        out = render_outline_tree(tmp_path / "x.pdf", chapters)
        # Returns a rich Tree; check it's truthy.
        assert out is not None

    def test_chapters_to_json_dict(self, tmp_path: Path) -> None:
        from capmd.cli_render import chapters_to_json_dict
        from capmd.models import Chapter

        chapters = [
            Chapter(title="A", level=1, start_page=1, end_page=2, index=1),
        ]
        data = chapters_to_json_dict(tmp_path / "x.pdf", chapters, total_pages=10)
        assert isinstance(data, dict)
        assert "chapters" in data


# ---------------------------------------------------------------------------
# report.py
# ---------------------------------------------------------------------------


class TestReportGaps:
    def test_collect_stats_basic(self) -> None:
        from capmd.report import collect_stats

        stats = collect_stats(
            raw_markdown="a" * 5000,
            final_markdown="a" * 4500,
            pages=10,
            figures_count=3,
            cleaner_stats=(),
            elapsed_seconds=1.5,
            source_format="pdf",
        )
        assert stats.pages == 10
        assert stats.figures == 3
        assert stats.cleaned_chars == 4500

    def test_collect_stats_with_cleaner_stats(self) -> None:
        from capmd.report import collect_stats

        stats = collect_stats(
            raw_markdown="a" * 1000,
            final_markdown="a" * 900,
            pages=5,
            figures_count=0,
            cleaner_stats=({"name": "headers", "changes": 5, "enabled": True},),
            elapsed_seconds=0.5,
            source_format="pdf",
        )
        assert stats.cleaners.total_changes == 5

    def test_collect_warnings_no_clean_over_cleanup(self) -> None:
        from capmd.report import collect_stats, collect_warnings

        stats = collect_stats(
            raw_markdown="a" * 100,
            final_markdown="a" * 10,  # 90% deletion
            pages=2,
            figures_count=0,
            cleaner_stats=(),
            elapsed_seconds=0.1,
            source_format="pdf",
        )
        # over_cleanup should fire (deletion_ratio > 0.5).
        warnings = collect_warnings(stats, no_clean=False, format="pdf")
        codes = [w["code"] for w in warnings]
        assert "over_cleanup" in codes

    def test_collect_warnings_no_clean_disables_over_cleanup(self) -> None:
        from capmd.report import collect_stats, collect_warnings

        stats = collect_stats(
            raw_markdown="a" * 100,
            final_markdown="a" * 10,
            pages=2,
            figures_count=0,
            cleaner_stats=(),
            elapsed_seconds=0.1,
            source_format="pdf",
        )
        warnings = collect_warnings(stats, no_clean=True, format="pdf")
        codes = [w["code"] for w in warnings]
        assert "over_cleanup" not in codes

    def test_collect_warnings_empty_output(self) -> None:
        from capmd.report import collect_stats, collect_warnings

        stats = collect_stats(
            raw_markdown="",
            final_markdown="",
            pages=5,
            figures_count=0,
            cleaner_stats=(),
            elapsed_seconds=0.1,
            source_format="pdf",
        )
        warnings = collect_warnings(stats, no_clean=False, format="pdf")
        codes = [w["code"] for w in warnings]
        assert "empty_output" in codes

    def test_collect_warnings_no_headings(self) -> None:
        from capmd.report import collect_stats, collect_warnings

        stats = collect_stats(
            raw_markdown="a" * 500,
            final_markdown="a" * 500,
            pages=5,
            figures_count=0,
            cleaner_stats=(),
            elapsed_seconds=0.1,
            source_format="pdf",
        )
        warnings = collect_warnings(stats, no_clean=False, format="pdf")
        codes = [w["code"] for w in warnings]
        assert "no_headings" in codes

    def test_render_json(self) -> None:
        from capmd.report import ReportOutput, collect_stats, render_json

        stats = collect_stats(
            raw_markdown="a" * 100,
            final_markdown="a" * 80,
            pages=5,
            figures_count=1,
            cleaner_stats=(),
            elapsed_seconds=0.5,
            source_format="pdf",
        )
        out = ReportOutput(schema_version=1, stats=stats, warnings=(), format="json")
        data = json.loads(render_json(out))
        assert data["stats"]["pages"] == 5
        assert data["report_schema_version"] == 1

    def test_render_text(self) -> None:
        from capmd.report import ReportOutput, collect_stats, render_text

        stats = collect_stats(
            raw_markdown="a" * 100,
            final_markdown="a" * 80,
            pages=5,
            figures_count=1,
            cleaner_stats=(),
            elapsed_seconds=0.5,
            source_format="pdf",
        )
        out = ReportOutput(schema_version=1, stats=stats, warnings=(), format="text")
        text = render_text(out)
        assert "5" in text  # pages count somewhere


# ---------------------------------------------------------------------------
# cli.py small gaps
# ---------------------------------------------------------------------------


class TestCliSmallGaps:
    def test_version_command(self) -> None:
        from typer.testing import CliRunner

        from capmd.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0

    def test_help_lists_convert(self) -> None:
        from typer.testing import CliRunner

        from capmd.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "convert" in result.stdout.lower() or "Usage" in result.stdout


# ---------------------------------------------------------------------------
# images/extract.py
# ---------------------------------------------------------------------------


class TestExtractGaps:
    def test_extract_options_invalid_format(self) -> None:
        from capmd.images.extract import ExtractOptions

        with pytest.raises(ValueError, match="formato no soportado"):
            ExtractOptions(image_format="gif")

    def test_extract_options_invalid_max_width(self) -> None:
        from capmd.images.extract import ExtractOptions

        with pytest.raises(ValueError, match="max_width debe ser > 0"):
            ExtractOptions(max_width=0)

    def test_extract_candidates_non_pdf(self, tmp_path: Path) -> None:
        from capmd.images.extract import extract_candidates

        with pytest.raises(ValueError, match="solo se extraen imágenes de PDF"):
            extract_candidates(tmp_path / "x.txt", [1])

    def test_extract_candidates_invalid_max_width(self, tmp_path: Path) -> None:
        from capmd.images.extract import extract_candidates

        with pytest.raises(ValueError, match="max_width debe ser > 0"):
            extract_candidates(tmp_path / "x.pdf", [1], max_width=0)

    def test_extract_candidates_empty_pages(self, tmp_path: Path) -> None:
        from capmd.images.extract import extract_candidates

        assert extract_candidates(tmp_path / "x.pdf", []) == []

    def test_make_figure_name_invalid_chapter(self) -> None:
        from capmd.images.extract import make_figure_name

        with pytest.raises(ValueError, match="chapter_index"):
            make_figure_name(0, 1, "png")

    def test_make_figure_name_invalid_index(self) -> None:
        from capmd.images.extract import make_figure_name

        with pytest.raises(ValueError, match="figure_index"):
            make_figure_name(1, 0, "png")

    def test_make_figure_name_three_digit_padding(self) -> None:
        from capmd.images.extract import make_figure_name

        assert make_figure_name(100, 200, "png") == "fig-100-200.png"

    def test_write_figures_invalid_format(self, tmp_path: Path) -> None:
        from capmd.images.extract import write_figures

        with pytest.raises(ValueError, match="formato no soportado"):
            write_figures([], tmp_path / "out", image_format="gif")

    def test_extract_figures_invalid_format(self, tmp_path: Path) -> None:
        from capmd.images.extract import ExtractOptions, extract_figures

        with pytest.raises(ValueError, match="formato no soportado"):
            extract_figures(
                tmp_path / "x.pdf",
                [1],
                tmp_path / "out",
                options=ExtractOptions(image_format="gif"),
            )


# ---------------------------------------------------------------------------
# images/anchor.py — branches no cubiertas
# ---------------------------------------------------------------------------


class TestAnchorGaps:
    def test_anchor_empty_figures(self) -> None:
        from capmd.images.anchor import anchor_figures

        # No figures → markdown intacto.
        out = anchor_figures(
            markdown="line1\nline2",
            figures=[],
            page_areas={},
        )
        assert out == "line1\nline2"

    def test_anchor_figure_with_no_page_areas(self) -> None:
        from capmd.images.anchor import anchor_figures
        from capmd.models import Figure

        # Figure con página sin area → cae al final del bloque.
        fig = Figure(
            chapter_index=1,
            index=1,
            path=Path("/tmp/fake.png"),
            page=1,
            bbox=(0.1, 0.5, 0.5, 0.7),
        )
        out = anchor_figures(
            markdown="line1\nline2\nline3",
            figures=[fig],
            page_areas={},  # no area for page 1
        )
        assert "line1" in out
        assert "fake.png" in out or "images/fake.png" in out


# ---------------------------------------------------------------------------
# cli_render.py: extra helper coverage
# ---------------------------------------------------------------------------


class TestCliRenderCommands:
    def test_render_outline_with_no_chapters(self, tmp_path: Path) -> None:
        from capmd.cli_render import render_outline_tree

        out = render_outline_tree(tmp_path / "x.pdf", [])
        assert out is not None

    def test_render_outline_nested_levels(self, tmp_path: Path) -> None:
        from capmd.cli_render import render_outline_tree
        from capmd.models import Chapter

        chapters = [
            Chapter(title="L1-A", level=1, start_page=1, end_page=3, index=1),
            Chapter(title="L2-A", level=2, start_page=4, end_page=5, index=2),
            Chapter(title="L1-B", level=1, start_page=6, end_page=8, index=3),
        ]
        out = render_outline_tree(tmp_path / "x.pdf", chapters)
        assert out is not None
