"""Tier-resolver registry: the neutral seam the CLI uses to resolve the
feature tier of the current invocation.

The resolved tier is opaque to OSS (see ``core.seams.tier_resolver``'s
docstring), so these tests stand in for a real tier with plain sentinel
values rather than importing a paid tier enum."""

import pytest

from core.seams import tier_resolver

pytestmark = [pytest.mark.unit]

_SOME_TIER = object()
_OTHER_TIER = object()


@pytest.fixture(autouse=True)
def _reset_resolver():
    tier_resolver.clear_resolver()
    yield
    tier_resolver.clear_resolver()


def test_no_resolver_registered_defaults_to_none():
    assert tier_resolver.resolve_tier(object()) is None


def test_registered_resolver_is_used():
    tier_resolver.register_resolver(lambda args: _SOME_TIER)
    assert tier_resolver.resolve_tier(object()) is _SOME_TIER


def test_registered_resolver_receives_args():
    received = []
    tier_resolver.register_resolver(lambda args: received.append(args) or _SOME_TIER)
    sentinel = object()

    tier_resolver.resolve_tier(sentinel)

    assert received == [sentinel]


def test_registered_resolver_read_hook():
    def resolver(args):
        return _SOME_TIER

    tier_resolver.register_resolver(resolver)

    assert tier_resolver.registered_resolver() is resolver


def test_reregistration_is_last_wins():
    tier_resolver.register_resolver(lambda args: _SOME_TIER)
    tier_resolver.register_resolver(lambda args: _OTHER_TIER)

    assert tier_resolver.resolve_tier(object()) is _OTHER_TIER


def test_clear_resolver_reverts_to_default():
    tier_resolver.register_resolver(lambda args: _SOME_TIER)
    tier_resolver.clear_resolver()

    assert tier_resolver.resolve_tier(object()) is None
    assert tier_resolver.registered_resolver() is None


def test_resolver_that_raises_denies_instead_of_crashing():
    def broken_resolver(args):
        raise RuntimeError("corrupted license file")

    tier_resolver.register_resolver(broken_resolver)

    assert tier_resolver.resolve_tier(object()) is None
