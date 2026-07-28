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


def test_empty_entry_points_does_not_latch_loaded(monkeypatch):
    """Same latch bug as AlterGeneratorFactory, one layer up: a container
    that installs a paid package without its entry points reaching this
    process yet (documented: entry_points(group='dblift.features') can come
    back empty depending on install/import timing) must not have that empty
    result cached forever -- a later call, once the entry point actually
    resolves, must still be allowed to load it.
    """
    monkeypatch.setattr(feature_loading, "entry_points", lambda group: [])

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
