"""Tests for the ``dblift.features`` entry-point loader seam."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import core.seams.feature_loading as feature_loading
from core.seams.feature_loading import load_feature_extensions

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _reset_once_flag(monkeypatch):
    monkeypatch.setattr(feature_loading, "_features_loaded", False)
    monkeypatch.delenv("DBLIFT_DISABLE_CLI_EXTENSIONS", raising=False)


def _entry_point(name, register):
    entry_point = MagicMock()
    entry_point.name = name
    entry_point.load.return_value = register
    return entry_point


def test_no_entry_points_is_a_noop(monkeypatch):
    monkeypatch.setattr(feature_loading, "entry_points", lambda group: [])

    load_feature_extensions()  # must not raise


def test_entry_points_are_loaded_and_called(monkeypatch):
    calls = []
    monkeypatch.setattr(
        feature_loading,
        "entry_points",
        lambda group: [_entry_point("enterprise", lambda: calls.append("enterprise"))],
    )

    load_feature_extensions()

    assert calls == ["enterprise"]


def test_second_call_is_a_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(
        feature_loading,
        "entry_points",
        lambda group: [_entry_point("enterprise", lambda: calls.append("enterprise"))],
    )

    load_feature_extensions()
    load_feature_extensions()

    assert calls == ["enterprise"]


def test_disable_env_var_skips_loading(monkeypatch):
    calls = []
    monkeypatch.setattr(
        feature_loading,
        "entry_points",
        lambda group: [_entry_point("enterprise", lambda: calls.append("enterprise"))],
    )
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")

    load_feature_extensions()

    assert calls == []


def test_bad_plugin_does_not_break_the_others(monkeypatch):
    calls = []

    def boom():
        raise RuntimeError("bad plugin")

    monkeypatch.setattr(
        feature_loading,
        "entry_points",
        lambda group: [
            _entry_point("aaa-broken", boom),
            _entry_point("zzz-good", lambda: calls.append("zzz-good")),
        ],
    )

    load_feature_extensions()  # must not raise

    assert calls == ["zzz-good"]


def test_entry_points_load_in_tier_order(monkeypatch):
    calls = []
    monkeypatch.setattr(
        feature_loading,
        "entry_points",
        lambda group: [
            _entry_point("enterprise", lambda: calls.append("enterprise")),
            _entry_point("pro", lambda: calls.append("pro")),
        ],
    )

    load_feature_extensions()

    assert calls == ["pro", "enterprise"]


def test_empty_entry_points_does_not_latch_loaded_when_a_tier_package_is_installed(
    monkeypatch,
):
    """Same latch bug as AlterGeneratorFactory, one layer up: a container
    that installs a paid package without its entry points reaching this
    process yet (documented: entry_points(group='dblift.features') can come
    back empty depending on install/import timing) must not have that empty
    result cached forever -- a later call, once the entry point actually
    resolves, must still be allowed to load it.

    This is only the correct call when a tier package is actually installed
    (see ``test_empty_entry_points_latches_immediately_with_no_tier_package_
    installed`` below for why retrying forever is wrong when none is).
    """
    monkeypatch.setattr(feature_loading, "entry_points", lambda group: [])
    monkeypatch.setattr(feature_loading, "_any_tier_distribution_installed", lambda: True)

    load_feature_extensions()

    assert feature_loading._features_loaded is False, (
        "an empty entry-point result must not be latched as loaded, or a "
        "later call that WOULD find the real entry point never retries"
    )


def test_a_later_call_with_entry_points_available_succeeds_after_an_earlier_empty_call(
    monkeypatch,
):
    """Reproduces the race directly: first call sees no entry points,
    second call (as if the paid package's metadata resolved in between)
    must actually load and invoke it -- not stay a no-op because the first
    call already latched ``_features_loaded``.
    """
    calls = []
    monkeypatch.setattr(feature_loading, "entry_points", lambda group: [])
    monkeypatch.setattr(feature_loading, "_any_tier_distribution_installed", lambda: True)
    load_feature_extensions()
    assert calls == []

    monkeypatch.setattr(
        feature_loading,
        "entry_points",
        lambda group: [_entry_point("pro", lambda: calls.append("pro"))],
    )
    load_feature_extensions()

    assert calls == ["pro"]
    assert feature_loading._features_loaded is True


def test_empty_entry_points_latches_immediately_with_no_tier_package_installed(monkeypatch):
    """Bugbot finding on PR #67: OSS's own pyproject.toml declares the
    ``dblift.features`` entry-points group empty -- so for a pure-OSS
    install (no ``dblift-pro``/``dblift-enterprise`` distribution present
    at all), entry_points(group='dblift.features') coming back empty is not
    a race to retry, it's the permanent, correct state. Retrying forever
    means every ``load_feature_extensions()`` call -- CLI startup, and each
    ``DBLiftClient`` construction -- rescans importlib.metadata for the
    life of the process, contradicting the module's own "idempotent after
    the first pass" documentation.

    Mocks ``_any_tier_distribution_installed`` to ``False`` explicitly
    (rather than relying on neither ``dblift-pro`` nor ``dblift-enterprise``
    happening to be absent from whatever environment runs this test) so the
    pure-OSS case this test pins is hermetic, matching its two neighboring
    tests in this file.
    """
    monkeypatch.setattr(feature_loading, "entry_points", lambda group: [])
    monkeypatch.setattr(feature_loading, "_any_tier_distribution_installed", lambda: False)

    load_feature_extensions()

    assert feature_loading._features_loaded is True, (
        "with no paid tier package installed at all, an empty "
        "dblift.features result is permanent, not a race -- it must latch "
        "immediately instead of rescanning importlib.metadata forever"
    )


def test_broken_tier_distribution_metadata_does_not_crash_load_feature_extensions(
    monkeypatch,
):
    """A distribution matching a known tier name with corrupted/unreadable
    metadata (e.g. undecodable METADATA bytes from an interrupted install)
    must not crash startup -- ``entry_point.load()``/``register()``
    failures two lines above are already caught this way; the
    tier-distribution check added for the pure-OSS latch fix needs the same
    defensive posture, or a broken ``dblift-pro`` install would raise
    straight out of the very first ``load_feature_extensions()`` call.
    """

    def _broken_version(name):
        if name == "dblift-pro":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad metadata")
        raise feature_loading.PackageNotFoundError(name)

    monkeypatch.setattr(feature_loading, "entry_points", lambda group: [])
    monkeypatch.setattr(feature_loading, "version", _broken_version)

    load_feature_extensions()  # must not raise

    assert feature_loading._features_loaded is True, (
        "a broken tier distribution must be treated like 'not installed', "
        "not left unresolved forever"
    )
