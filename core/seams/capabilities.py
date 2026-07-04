"""Neutral capability-rejection seam.

OSS dispatch code (``cli/_command_handlers.py``) needs to catch "this
invocation isn't entitled to run this command" without importing any
paid-tier vocabulary (tier names, the feature registry). Higher tiers raise
their own tier-aware exception, which subclasses :class:`CapabilityDeniedError`
so the OSS catch-all stays neutral.
"""

from __future__ import annotations

from core.exceptions import DbliftError


class CapabilityDeniedError(DbliftError):
    """Raised when the current invocation isn't entitled to a capability.

    Higher tiers raise a subclass carrying tier-specific detail; OSS
    dispatch code only ever needs to catch this base type.
    """
