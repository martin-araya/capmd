"""Tests for capmd.convert.limits — ConversionLimits + parse_size."""

from __future__ import annotations

import pytest

from capmd.convert.limits import ConversionLimits, parse_size


class TestConversionLimitsValidation:
    def test_zero_max_size_bytes_raises(self) -> None:
        with pytest.raises(ValueError, match="max_size_bytes"):
            ConversionLimits(max_size_bytes=0)

    def test_zero_max_pages_raises(self) -> None:
        with pytest.raises(ValueError, match="max_pages"):
            ConversionLimits(max_pages=0)

    def test_zero_timeout_seconds_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout_seconds"):
            ConversionLimits(timeout_seconds=0)

    def test_zero_warn_pages_raises(self) -> None:
        with pytest.raises(ValueError, match="warn_pages"):
            ConversionLimits(warn_pages=0)


class TestParseSizeEdgeCases:
    def test_negative_after_multiplication_triggers_msg(self) -> None:
        # The regex won't match a literal "-" before digits; "-1G" fails pattern.
        with pytest.raises(ValueError):
            parse_size("-1G")

    def test_zero_size_triggers_msg(self) -> None:
        with pytest.raises(ValueError, match="menor a 1 byte"):
            parse_size("0")

    def test_non_string_input(self) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            parse_size(123)  # type: ignore[arg-type]

    def test_overflow_triggers_msg(self) -> None:
        # 10G = 10_000_000_000 (under 2^63 - 1 ~ 9.22e18); bump up.
        with pytest.raises(ValueError, match="overflow"):
            parse_size("10000000000G")  # 1e19 > 2^63 - 1

    def test_invalid_suffix_t(self) -> None:
        with pytest.raises(ValueError, match="tamaño inválido"):
            parse_size("1T")
