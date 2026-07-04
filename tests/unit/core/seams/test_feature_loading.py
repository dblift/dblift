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
