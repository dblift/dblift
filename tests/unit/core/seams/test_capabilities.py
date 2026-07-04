"""Neutral capability-rejection seam: the exception type OSS dispatch code
catches without importing any paid tier vocabulary."""

import pytest

from core.exceptions import DbliftError
from core.seams import capabilities

pytestmark = [pytest.mark.unit]


def test_capability_denied_error_is_an_exception():
    exc = capabilities.CapabilityDeniedError("requires a PRO license")
    assert isinstance(exc, Exception)
    assert str(exc) == "requires a PRO license"


def test_capability_denied_error_is_a_dblift_error():
    """So `except DbliftError` catch-alls don't silently miss capability
    rejections — every other domain exception hangs off this root."""
    assert isinstance(capabilities.CapabilityDeniedError("x"), DbliftError)


def test_paid_rejection_can_subclass_the_neutral_error():
    class PaidRejection(capabilities.CapabilityDeniedError):
        pass

    with pytest.raises(capabilities.CapabilityDeniedError):
        raise PaidRejection("nope")
