"""Tests del helper :func:`capmd.sources._pdfium.with_textpage`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from capmd.sources._pdfium import with_textpage


def test_with_textpage_returns_fn_result() -> None:
    """Happy path: el callback recibe el textpage y su return se propaga."""
    tp = MagicMock()
    page = MagicMock()
    page.get_textpage.return_value = tp

    result = with_textpage(page, lambda t: "computed-" + str(t is tp))

    assert result == f"computed-{tp is tp}"
    tp.close.assert_called_once()


def test_with_textpage_closes_on_exception() -> None:
    """BUGS.md LOW #10: si el callback levanta, tp.close() igual corre."""
    tp = MagicMock()
    page = MagicMock()
    page.get_textpage.return_value = tp

    def boom(_t: object) -> str:
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        with_textpage(page, boom)
    tp.close.assert_called_once()


def test_with_textpage_returns_none_when_get_textpage_fails() -> None:
    """Si ``page.get_textpage()`` levanta, devuelve None (no propaga)."""
    page = MagicMock()
    page.get_textpage.side_effect = OSError("pdfium kaput")

    result = with_textpage(page, lambda tp: "should not run")

    assert result is None


def test_with_textpage_swallows_close_errors() -> None:
    """Si ``tp.close()`` levanta, no propagamos (defensivo)."""
    tp = MagicMock()
    tp.close.side_effect = OSError("close failed")
    page = MagicMock()
    page.get_textpage.return_value = tp

    result = with_textpage(page, lambda t: 42)

    assert result == 42
    tp.close.assert_called_once()
