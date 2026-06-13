"""Tests for TextFormatter.format_header license_info rendering."""

import pytest

from core.logger.log import TextFormatter

pytestmark = [pytest.mark.unit]


def _make_info(days=90, expires="2026-01-01"):
    return {
        "customer_name": "Jane Smith",
        "customer_email": "jane@example.com",
        "expires_at": expires,
        "days_remaining": days,
    }


class TestTextFormatterLicenseInfo:
    def test_no_license_info_omits_licensed_to(self):
        fmt = TextFormatter()
        fmt.license_info = None
        header = fmt.format_header(schema="public", database_name="mydb")
        assert "Licensed to" not in header

    def test_license_info_shows_customer(self):
        fmt = TextFormatter()
        fmt.license_info = _make_info()
        header = fmt.format_header()
        assert "Licensed to: Jane Smith (jane@example.com)" in header

    def test_license_info_with_days_remaining(self):
        fmt = TextFormatter()
        fmt.license_info = _make_info(days=90, expires="2026-01-01")
        header = fmt.format_header()
        assert "2026-01-01 (90 days remaining)" in header

    def test_license_info_perpetual_no_days(self):
        fmt = TextFormatter()
        fmt.license_info = {
            "customer_name": "Bob",
            "customer_email": "bob@example.com",
            "expires_at": "Never",
            "days_remaining": None,
        }
        header = fmt.format_header()
        assert "License expires: Never" in header
        assert "days remaining" not in header

    def test_license_info_zero_days_remaining(self):
        fmt = TextFormatter()
        fmt.license_info = _make_info(days=0, expires="2025-04-09")
        header = fmt.format_header()
        assert "0 days remaining" in header

    def test_license_info_does_not_appear_before_separator(self):
        """License info appears after the header separator, not before."""
        fmt = TextFormatter()
        fmt.license_info = _make_info()
        header = fmt.format_header()
        sep_pos = header.index("-" * 10)
        license_pos = header.index("Licensed to")
        assert license_pos > sep_pos
