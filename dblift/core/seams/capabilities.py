"""Neutral capability-rejection seam.

OSS dispatch code (``cli/_command_handlers.py``) needs to catch "this
invocation isn't entitled to run this command" without importing any
add-on vocabulary. An add-on package raises its own subclass of
:class:`CapabilityDeniedError`, so the catch-all here stays neutral.
"""

from __future__ import annotations

from dblift.core.exceptions import DbliftError


class CapabilityDeniedError(DbliftError):
    """Raised when the current invocation isn't entitled to a capability.

    Add-on packages raise a subclass carrying their own detail; dispatch
    code only ever needs to catch this base type.
    """
