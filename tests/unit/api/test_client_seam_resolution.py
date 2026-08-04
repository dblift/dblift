"""``DBLiftClient.from_config`` / ``from_config_file`` / ``from_sqlalchemy``
consult the ``dblift.client`` tier-resolution seam (issue #753).

The CLI already resolves its client class through
``core.seams.client_factory.resolve_client_class()`` (see
``tests/unit/core/seams/test_client_factory.py`` and
``tests/unit/cli/test_build_command_client.py`` for the seam's own
coverage). The documented programmatic entry point
(``from api.client import DBLiftClient``) did not: its factory classmethods
always constructed whatever class they were invoked on, so a bare
``DBLiftClient.from_config(...)`` could never pick up a tier-provided
subclass even when one was registered. These tests pin the fix at the
classmethod level, following the same fake-entry-point / monkeypatch style
as the seam's own tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.client import DBLiftClient
from core.seams import client_factory

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_resolution():
    client_factory._reset_for_tests()
    yield
    client_factory._reset_for_tests()


def _make_config(directory="migrations"):
    config = MagicMock()
    config.migrations.directory = directory
    config.migrations.directories = []
    config.log_format = None
    config.log_level = None
    config.log_file = None
    config.log_dir = None
    config.logging = MagicMock()
    config.logging.directory = None
    config.logging.file = None
    config.database.type = "postgresql"
    return config


def _factory_patches():
    """Patch the DB/logging side effects factory functions trigger before
    ever reaching the class-resolution decision under test."""
    return (
        patch(
            "api._client_factory.ProviderRegistry.create_provider", return_value=MagicMock(spec=[])
        ),
        patch("api._client_factory.DbliftLogger", return_value=MagicMock()),
    )


class _UpgradedClient:
    """Stand-in for a tier-provided ``DBLiftClient`` subclass registered on
    the ``dblift.client`` seam."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _OSSSubclass(DBLiftClient):
    """A concrete subclass of the OSS client, constructed directly by a
    caller — proves the seam never overrides an already-specific class."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.mark.unit
class TestFromConfigSeamResolution:
    def test_base_class_upgrades_when_seam_registered(self, monkeypatch):
        monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _UpgradedClient)
        p1, p2 = _factory_patches()
        with p1, p2:
            client = DBLiftClient.from_config(_make_config())
        assert isinstance(client, _UpgradedClient)

    def test_base_class_falls_back_to_oss_without_registration(self, monkeypatch):
        monkeypatch.setattr(client_factory, "entry_points", lambda group: [])
        p1, p2 = _factory_patches()
        captured = {}

        def fake_init(self, **kwargs):
            captured.update(kwargs)

        with p1, p2, patch.object(DBLiftClient, "__init__", fake_init):
            client = DBLiftClient.from_config(_make_config())
        assert type(client) is DBLiftClient

    def test_subclass_is_not_overridden_by_seam(self, monkeypatch):
        monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _UpgradedClient)
        p1, p2 = _factory_patches()
        with p1, p2:
            client = _OSSSubclass.from_config(_make_config())
        assert isinstance(client, _OSSSubclass)
        assert not isinstance(client, _UpgradedClient)


@pytest.mark.unit
class TestFromConfigFileSeamResolution:
    def test_base_class_upgrades_when_seam_registered(self, monkeypatch):
        monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _UpgradedClient)
        p1, p2 = _factory_patches()
        with (
            p1,
            p2,
            patch("api._client_factory.ConfigBuilder.build", return_value=_make_config()),
        ):
            client = DBLiftClient.from_config_file("dblift.yaml")
        assert isinstance(client, _UpgradedClient)

    def test_base_class_falls_back_to_oss_without_registration(self, monkeypatch):
        monkeypatch.setattr(client_factory, "entry_points", lambda group: [])
        p1, p2 = _factory_patches()
        captured = {}

        def fake_init(self, **kwargs):
            captured.update(kwargs)

        with (
            p1,
            p2,
            patch("api._client_factory.ConfigBuilder.build", return_value=_make_config()),
            patch.object(DBLiftClient, "__init__", fake_init),
        ):
            client = DBLiftClient.from_config_file("dblift.yaml")
        assert type(client) is DBLiftClient

    def test_subclass_is_not_overridden_by_seam(self, monkeypatch):
        monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _UpgradedClient)
        p1, p2 = _factory_patches()
        with (
            p1,
            p2,
            patch("api._client_factory.ConfigBuilder.build", return_value=_make_config()),
        ):
            client = _OSSSubclass.from_config_file("dblift.yaml")
        assert isinstance(client, _OSSSubclass)
        assert not isinstance(client, _UpgradedClient)


@pytest.mark.unit
class TestFromSqlalchemySeamResolution:
    def test_base_class_upgrades_when_seam_registered(self, monkeypatch):
        monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _UpgradedClient)
        p1, p2 = _factory_patches()
        with (
            p1,
            p2,
            patch("api._client_factory.config_from_engine", return_value=_make_config()),
        ):
            client = DBLiftClient.from_sqlalchemy(engine=MagicMock(spec=[]))
        assert isinstance(client, _UpgradedClient)

    def test_base_class_falls_back_to_oss_without_registration(self, monkeypatch):
        monkeypatch.setattr(client_factory, "entry_points", lambda group: [])
        p1, p2 = _factory_patches()

        def fake_init(self, **kwargs):
            pass

        with (
            p1,
            p2,
            patch("api._client_factory.config_from_engine", return_value=_make_config()),
            patch.object(DBLiftClient, "__init__", fake_init),
        ):
            client = DBLiftClient.from_sqlalchemy(engine=MagicMock(spec=[]))
        assert type(client) is DBLiftClient

    def test_subclass_is_not_overridden_by_seam(self, monkeypatch):
        monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _UpgradedClient)
        p1, p2 = _factory_patches()
        with (
            p1,
            p2,
            patch("api._client_factory.config_from_engine", return_value=_make_config()),
        ):
            client = _OSSSubclass.from_sqlalchemy(engine=MagicMock(spec=[]))
        assert isinstance(client, _OSSSubclass)
        assert not isinstance(client, _UpgradedClient)
