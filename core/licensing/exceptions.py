"""Licensing exceptions for dblift."""

from core.exceptions import DbliftError


class LicenseError(DbliftError):
    """Base exception for all licensing errors."""


class LicenseInvalidError(LicenseError):
    """Raised when a license token cannot be decoded or has an invalid signature."""


class LicenseExpiredError(LicenseError):
    """Raised when a license token has passed its expiration date."""
