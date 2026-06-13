"""Shared fixtures for CLI tests.

Provides a valid test license token so that subprocess-based CLI tests
pass the license gate. The token is signed with the production private
key (from .dblift_private_key.pem) so it validates against the embedded
public key. If the private key file is not available, the license gate
is bypassed via monkeypatching for in-process tests.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

from core.licensing.license_manager import License

# Try to load the production private key for signing test tokens
_PRIVATE_KEY_PATH = Path(__file__).parent.parent.parent.parent / ".dblift_private_key.pem"
_TEST_TOKEN = None

if _PRIVATE_KEY_PATH.exists():
    _private_key = _PRIVATE_KEY_PATH.read_text()
    _now = datetime.now(timezone.utc)
    _TEST_TOKEN = jwt.encode(
        {
            "sub": "test@dblift.com",
            "name": "Test License",
            "iat": _now,
            "jti": str(uuid.uuid4()),
            "exp": _now + timedelta(days=365),
        },
        _private_key,
        algorithm="RS256",
    )


@pytest.fixture(autouse=True)
def _license_env_for_subprocess(monkeypatch):
    """Set DBLIFT_LICENSE_KEY so subprocess CLI invocations pass the license gate."""
    if _TEST_TOKEN:
        monkeypatch.setenv("DBLIFT_LICENSE_KEY", _TEST_TOKEN)
    else:
        # No private key available — patch the license gate for in-process tests
        monkeypatch.setenv("DBLIFT_LICENSE_KEY", "dummy")
        _stub_license = License(
            customer_name="Test",
            customer_email="test@test.com",
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            license_id="test-stub",
        )
        monkeypatch.setattr(
            "core.licensing.license_manager.LicenseManager.resolve",
            lambda self, cli_token=None: _stub_license,
        )
        monkeypatch.setattr(
            "core.licensing.license_manager.LicenseManager.get_info",
            lambda self, cli_token=None: {
                "customer_name": "Test",
                "customer_email": "test@test.com",
                "issued_at": "2026-01-01",
                "expires_at": "2027-01-01",
                "days_remaining": 365,
                "license_id": "test",
            },
        )
