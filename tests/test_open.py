"""Tests de ``capmd.open`` (H5)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from capmd.cli import app
from capmd.errors import SourceNotFound
from capmd.open import open_in_editor, resolve_editor_command

# ---------------------------------------------------------------------------
# resolve_editor_command
# ---------------------------------------------------------------------------


class TestResolveEditorCommand:
    def test_editor_arg_wins_env(self) -> None:
        """``editor`` arg gana sobre ``$EDITOR``."""
        result = resolve_editor_command(
            "code --wait",
            platform="darwin",
            env_editor="vim",
        )
        assert result == ["code", "--wait"]

    def test_editor_arg_quoted_split(self) -> None:
        result = resolve_editor_command(
            "code --wait --new-window",
            platform="darwin",
            env_editor=None,
        )
        assert result == ["code", "--wait", "--new-window"]

    def test_env_var_fallback(self) -> None:
        result = resolve_editor_command(
            None,
            platform="darwin",
            env_editor="vim",
        )
        assert result == ["vim"]

    def test_env_var_quoted_split(self) -> None:
        result = resolve_editor_command(
            None,
            platform="darwin",
            env_editor="code --wait",
        )
        assert result == ["code", "--wait"]

    def test_darwin_no_editor_falls_back_to_open(self) -> None:
        result = resolve_editor_command(
            None,
            platform="darwin",
            env_editor=None,
        )
        assert result == ["open"]

    def test_linux_no_editor_raises(self) -> None:
        import typer

        with pytest.raises(typer.BadParameter) as excinfo:
            resolve_editor_command(
                None,
                platform="linux",
                env_editor=None,
            )
        assert "EDITOR" in str(excinfo.value) or "editor" in str(excinfo.value)

    def test_invalid_editor_string_raises(self) -> None:
        """shlex.split puede fallar con quotes mal cerrados."""
        import typer

        with pytest.raises(typer.BadParameter):
            resolve_editor_command(
                'code "unclosed',
                platform="darwin",
                env_editor=None,
            )


# ---------------------------------------------------------------------------
# open_in_editor con Popen mockeado
# ---------------------------------------------------------------------------


class TestOpenInEditor:
    def test_invokes_editor_with_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "out.md"
        target.write_text("# hello\n")
        spawn = MagicMock()
        open_in_editor(
            target,
            editor="vim",
            spawn=spawn,
            platform="linux",
        )
        spawn.assert_called_once()
        args, kwargs = spawn.call_args
        assert args[0] == ["vim", str(target)]
        # Fire-and-forget: stdin/stdout/stderr NO son la stdin del capmd.
        assert kwargs.get("stdin") is subprocess.DEVNULL
        assert kwargs.get("stdout") is subprocess.DEVNULL
        assert kwargs.get("stderr") is subprocess.DEVNULL

    def test_darwin_invokes_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "out.md"
        target.write_text("hola")
        spawn = MagicMock()
        open_in_editor(
            target,
            spawn=spawn,
            platform="darwin",
            env_editor=None,
        )
        args, _ = spawn.call_args
        assert args[0] == ["open", str(target)]

    def test_does_not_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``open_in_editor`` no llama ``.wait()`` (fire-and-forget)."""
        target = tmp_path / "out.md"
        target.write_text("hi")
        proc_mock = MagicMock()
        spawn_mock = MagicMock(return_value=proc_mock)
        open_in_editor(
            target,
            editor="vim",
            spawn=spawn_mock,
            platform="linux",
        )
        proc_mock.wait.assert_not_called()

    def test_nonexistent_path_raises_source_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawn = MagicMock()
        with pytest.raises(SourceNotFound):
            open_in_editor(
                Path("/does/not/exist.md"),
                editor="vim",
                spawn=spawn,
                platform="linux",
            )
        spawn.assert_not_called()

    def test_no_editor_linux_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "out.md"
        target.write_text("x")
        import typer
        with pytest.raises(typer.BadParameter):
            open_in_editor(
                target,
                spawn=MagicMock(),
                platform="linux",
                env_editor=None,
            )

    def test_editor_binary_missing_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Si el binario del editor no existe en PATH, ``Popen`` levanta
        ``FileNotFoundError`` y lo dejamos propagar (el caller lo mapea
        a exit 2 en el CLI)."""
        target = tmp_path / "out.md"
        target.write_text("x")

        def fake_spawn(*_args, **_kwargs):
            raise FileNotFoundError(2, "No such file", "ghost-edit")

        with pytest.raises(FileNotFoundError):
            open_in_editor(
                target,
                editor="ghost-edit",
                spawn=fake_spawn,
                platform="linux",
            )

    def test_real_subprocess_popen_no_wait_no_error(
        self, tmp_path: Path
    ) -> None:
        """Smoke con subprocess real: invoca ``true`` (que no falla) y
        no espera. Sin aserción dura sobre ``wait``; basta con que no
        tire excepción."""
        target = tmp_path / "real.md"
        target.write_text("hi")
        # ``true`` está en PATH en POSIX; si no está, skip.
        if not __import__("shutil").which("true"):
            pytest.skip("'true' no disponible")
        # Redirigimos stdout/stderr para no contaminar el test runner.
        try:
            open_in_editor(
                target,
                editor="true",
                platform="linux",
            )
        except FileNotFoundError:
            pytest.skip("editor 'true' no encontrado")


# ---------------------------------------------------------------------------
# E2E (capmd open + convert --open)



# ---------------------------------------------------------------------------
# E2E (capmd open + convert --open)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_popen(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patchea ``subprocess.Popen`` para que ``capmd open`` y ``capmd
    convert --open`` no abran nada real."""
    mock = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock)
    return mock


def _build_pdf(tmp_path: Path, name: str = "x.pdf") -> Path:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as cm

    p = tmp_path / name
    c = cm.Canvas(str(p), pagesize=LETTER)
    c.setFont("Helvetica", 12)
    c.drawString(72, 720, "Hello world")
    c.showPage()
    c.save()
    return p


class TestCapmdOpenSubcommand:
    def test_help_lists_open(self) -> None:
        r = CliRunner().invoke(app, ["open", "--help"])
        assert r.exit_code == 0
        assert "--editor" in r.stdout
        assert "--quiet" in r.stdout

    def test_open_invokes_editor(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        target = tmp_path / "out.md"
        target.write_text("# hello\n")
        result = CliRunner().invoke(app, ["open", str(target)])
        assert result.exit_code == 0, result.stderr
        fake_popen.assert_called_once()
        args, _ = fake_popen.call_args
        assert args[0] == ["open", str(target)]

    def test_open_with_editor_flag(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        target = tmp_path / "out.md"
        target.write_text("# hello\n")
        result = CliRunner().invoke(
            app, ["open", str(target), "--editor", "code --wait"]
        )
        assert result.exit_code == 0, result.stderr
        fake_popen.assert_called_once()
        args, _ = fake_popen.call_args
        assert args[0] == ["code", "--wait", str(target)]

    def test_open_nonexistent_exits_2(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app, ["open", str(tmp_path / "nope.md")]
        )
        assert result.exit_code == 2

    def test_open_quiet_keeps_stderr_empty(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        target = tmp_path / "out.md"
        target.write_text("x")
        result = CliRunner().invoke(app, ["--quiet", "open", str(target)])
        assert result.exit_code == 0
        assert result.stderr == ""


class TestConvertOpenFlag:
    def test_convert_open_invokes_editor_with_written_md(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        pdf = _build_pdf(tmp_path)
        out = tmp_path / "out.md"
        result = CliRunner().invoke(
            app,
            ["--quiet", "convert", str(pdf), "-o", str(out), "--open"],
        )
        assert result.exit_code == 0, result.stderr
        out_md = tmp_path / "out.md"
        assert out_md.exists()
        fake_popen.assert_called_once()
        args, _ = fake_popen.call_args
        assert args[0][-1] == str(out_md)

    def test_convert_open_with_out_tree_invokes_editor_with_chapter_md(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        from tests.fixtures import build as fix_build

        pdf = fix_build.build_outline_toc_pdf(tmp_path / "book.pdf")
        out_dir = tmp_path / "out"
        result = CliRunner().invoke(
            app,
            ["--quiet", "convert", str(pdf), "--out", str(out_dir), "--open"],
        )
        assert result.exit_code == 0, result.stderr
        fake_popen.assert_called_once()
        args, _ = fake_popen.call_args
        opened = args[0][-1]
        assert Path(opened).exists()
        assert opened.endswith(".md")

    def test_convert_open_dry_run_does_not_invoke_editor(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        pdf = _build_pdf(tmp_path)
        out_dir = tmp_path / "dry"
        result = CliRunner().invoke(
            app,
            [
                "--quiet",
                "convert",
                str(pdf),
                "--out",
                str(out_dir),
                "--dry-run",
                "--open",
            ],
        )
        assert result.exit_code == 0, result.stderr
        fake_popen.assert_not_called()

    def test_convert_open_with_stdin_does_not_invoke_editor(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        CliRunner().invoke(
            app,
            ["--quiet", "convert", "-", "--ext", "pdf", "--open"],
            input=b"%PDF-1.4\n",
        )
        fake_popen.assert_not_called()

    def test_convert_open_cmd_override(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        pdf = _build_pdf(tmp_path)
        out = tmp_path / "out.md"
        result = CliRunner().invoke(
            app,
            [
                "--quiet",
                "convert",
                str(pdf),
                "-o",
                str(out),
                "--open",
                "--open-cmd",
                "code --wait",
            ],
        )
        assert result.exit_code == 0, result.stderr
        fake_popen.assert_called_once()
        args, _ = fake_popen.call_args
        assert args[0][:-1] == ["code", "--wait"]
        assert args[0][-1] == str(out)

    def test_convert_without_open_does_not_invoke_editor(
        self, tmp_path: Path, fake_popen: MagicMock
    ) -> None:
        pdf = _build_pdf(tmp_path)
        out = tmp_path / "out.md"
        result = CliRunner().invoke(
            app,
            ["--quiet", "convert", str(pdf), "-o", str(out)],
        )
        assert result.exit_code == 0
        fake_popen.assert_not_called()

    def test_convert_open_help_mentions_flag(self) -> None:
        result = CliRunner().invoke(app, ["convert", "--help"])
        assert result.exit_code == 0
        assert "--open" in result.stdout
        assert "--open-cmd" in result.stdout
