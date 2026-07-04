"""License-banner rendering in TextFormatter.

The banner is inert in a pure OSS install — ``license_info`` stays ``None``
because no provider is registered on the ``core.seams.license_info`` seam.
A higher tier that registers a provider populates it and the banner renders.
These tests cover the rendering itself (OSS-side), independent of any provider.
"""

import pytest

from core.logger._formatters import TextFormatter

pytestmark = [pytest.mark.unit]


def test_no_banner_when_license_info_absent():
    """Pure OSS: no provider → license_info None → header has no banner."""
    formatter = TextFormatter()
    header = formatter.format_header()
    assert "Licensed to:" not in header
    assert "License expires:" not in header


def test_banner_renders_name_email_and_expiry_with_days():
    formatter = TextFormatter()
    formatter.license_info = {
        "customer_name": "Jane Smith",
        "customer_email": "jane@example.com",
        "expires_at": "2026-01-01",
        "days_remaining": 90,
    }
    header = formatter.format_header()
    assert "Licensed to: Jane Smith (jane@example.com)" in header
    assert "License expires: 2026-01-01 (90 days remaining)" in header


def test_banner_renders_expiry_without_days_remaining():
    formatter = TextFormatter()
    formatter.license_info = {
        "customer_name": "Acme Corp",
        "customer_email": "ops@acme.example",
        "expires_at": "Never",
    }
    header = formatter.format_header()
    assert "Licensed to: Acme Corp (ops@acme.example)" in header
    assert "License expires: Never" in header
    assert "days remaining" not in header


def test_banner_defaults_missing_fields():
    formatter = TextFormatter()
    formatter.license_info = {}
    header = formatter.format_header()
    # Empty dict is falsy → no banner at all.
    assert "Licensed to:" not in header
