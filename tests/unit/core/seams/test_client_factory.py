"""Unit tests for the ``dblift.client`` client-factory seam."""

from __future__ import annotations

import pytest

from dblift.core.seams import client_factory

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_resolution():
    client_factory._reset_for_tests()
    yield
    client_factory._reset_for_tests()


class _FakeEntryPoint:
    def __init__(self, name, payload, raises=False):
        self.name = name
        self._payload = payload
        self._raises = raises

    def load(self):
        if self._raises:
            raise RuntimeError("boom")
        return self._payload


class _TierClient:
    @classmethod
    def from_config(cls, config, logger=None):
        return cls()


def test_falls_back_to_oss_client_without_registration(monkeypatch):
    monkeypatch.setattr(client_factory, "entry_points", lambda group: [])
    from dblift.api import DBLiftClient

    assert client_factory.resolve_client_class() is DBLiftClient


def test_registered_class_wins(monkeypatch):
    monkeypatch.setattr(
        client_factory,
        "entry_points",
        lambda group: [_FakeEntryPoint("tier", _TierClient)],
    )
    assert client_factory.resolve_client_class() is _TierClient


def test_resolution_is_cached(monkeypatch):
    calls = []

    def _entry_points(group):
        calls.append(group)
        return [_FakeEntryPoint("tier", _TierClient)]

    monkeypatch.setattr(client_factory, "entry_points", _entry_points)
    client_factory.resolve_client_class()
    client_factory.resolve_client_class()
    assert calls == [client_factory.ENTRY_POINT_GROUP]


def test_broken_plugin_falls_back(monkeypatch):
    monkeypatch.setattr(
        client_factory,
        "entry_points",
        lambda group: [_FakeEntryPoint("bad", None, raises=True)],
    )
    from dblift.api import DBLiftClient

    assert client_factory.resolve_client_class() is DBLiftClient


def test_non_class_payload_is_ignored(monkeypatch):
    monkeypatch.setattr(
        client_factory,
        "entry_points",
        lambda group: [
            _FakeEntryPoint("bad", object()),
            _FakeEntryPoint("good", _TierClient),
        ],
    )
    assert client_factory.resolve_client_class() is _TierClient
