"""Conftest de capmd (J2).

Agrega ``--update-golden`` como alias de ``--snapshot-update`` de syrupy
y redefine el fixture ``snapshot`` con un ``MarkdownSnapshotExtension``
custom que escribe ``tests/golden/<name>.md`` (en vez del default
``__snapshots__/<name>.ambr``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from syrupy.constants import TEXT_ENCODING
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


class MarkdownSnapshotExtension(SingleFileSnapshotExtension):
    """SingleFileSnapshotExtension con extension ``.md`` y directorio forzado."""

    _file_extension = "md"
    _write_mode = WriteMode.TEXT
    _text_encoding = TEXT_ENCODING

    @classmethod
    def dirname(cls, *, test_location):
        """Apunta a ``tests/golden/<test_module>/`` (un subdir por test file).

        Esto satisface el chequeo de syrupy sobre ``test_location.basename``
        y silencia el UserWarning sobre "not relate".
        """
        return str(GOLDEN_DIR / test_location.basename.replace(".py", ""))

    @classmethod
    def get_snapshot_name(cls, *, test_location, index=0):
        """Si el test pasa ``snapshot(name=...)``, usamos ese name literal.

        El caller (``test_golden_pipeline.py``) siempre pasa un name
        que ya incluye el test id (``<fixture>``). Lo usamos directo.
        """
        if isinstance(index, str) and index:
            return index
        return super().get_snapshot_name(test_location=test_location, index=index)


@pytest.fixture
def snapshot(snapshot):  # type: ignore[no-redef]
    """Override del fixture ``snapshot`` built-in de syrupy.

    Aplica nuestro serializer custom para que ``assert md == snapshot(...)``
    escriba ``tests/golden/<name>.md`` en vez del default ``__snapshots__/<name>.ambr``.
    """
    return snapshot.use_extension(MarkdownSnapshotExtension)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("capmd", description="capmd-specific test options")
    group.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "Regenera los goldens en tests/golden/. "
            "Sinonimo de --snapshot-update de syrupy."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Translate ``--update-golden`` to syrupy's ``--snapshot-update``.

    syrupy registra la flag con ``dest="update_snapshots"`` (no
    ``snapshot_update``); por eso escribimos ``config.option.update_snapshots``.
    """
    if config.getoption("--update-golden"):
        config.option.update_snapshots = True
