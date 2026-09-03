"""``MongoDbConnectionManager`` — owns the driver handles.

``.client`` and ``.database`` are load-bearing names: MigrationContext.db
and .raw_client resolve against exactly these attributes.
"""

from unittest.mock import MagicMock, patch

import pytest

from dblift.config import DbliftConfig
from dblift.db.plugins.mongodb.config import MongoDbConfig
from dblift.db.plugins.mongodb.mongodb import MongoDbConnectionManager


def _config(**overrides):
    database = MongoDbConfig(
        type="mongodb",
        url=overrides.pop("url", "mongodb://localhost:27017"),
        database=overrides.pop("database", "appdb"),
        **overrides,
    )
    config = MagicMock(spec=DbliftConfig)
    config.database = database
    return config


def test_handles_start_empty():
    manager = MongoDbConnectionManager(_config())
    assert manager.client is None
    assert manager.database is None


def _patch_mongo_client(fake_client):
    """Patch the production import seam — unit CI may not have pymongo until
    the ``mongodb`` extra is installed, and ``patch("pymongo.MongoClient")``
    fails to resolve without the package on the path."""
    return patch(
        "dblift.db.plugins.mongodb.mongodb.connection_manager._load_mongo_client",
        return_value=MagicMock(return_value=fake_client),
    )


def test_create_connection_sets_both_handles():
    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    fake_database = MagicMock()
    fake_client.__getitem__.return_value = fake_database

    with _patch_mongo_client(fake_client) as loader:
        returned = manager.create_connection()

    loader.assert_called_once()
    mongo_client = loader.return_value
    mongo_client.assert_called_once()
    assert mongo_client.call_args.args[0] == "mongodb://localhost:27017"
    assert manager.client is fake_client
    assert manager.database is fake_database
    assert returned is fake_database


def test_create_connection_pings_the_server():
    """pymongo's MongoClient() constructor never raises for a bad host — it
    connects lazily. Without an explicit ping, create_connection() cannot
    detect an unreachable server, and db check-connection would report
    success against a host with nothing listening."""
    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    with _patch_mongo_client(fake_client):
        manager.create_connection()
    fake_client.admin.command.assert_called_once_with("ping")


def test_create_connection_raises_when_the_server_is_unreachable():
    pytest.importorskip("pymongo")
    from pymongo.errors import ServerSelectionTimeoutError

    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    fake_client.admin.command.side_effect = ServerSelectionTimeoutError("no servers found")
    with _patch_mongo_client(fake_client):
        with pytest.raises(ServerSelectionTimeoutError):
            manager.create_connection()


def test_database_is_selected_by_name():
    manager = MongoDbConnectionManager(_config(database="appdb"))
    fake_client = MagicMock()
    with _patch_mongo_client(fake_client):
        manager.create_connection()
    fake_client.__getitem__.assert_called_once_with("appdb")


def test_missing_driver_gives_an_install_hint():
    manager = MongoDbConnectionManager(_config())
    with patch("dblift.db.plugins.mongodb.mongodb.connection_manager._load_mongo_client") as loader:
        loader.side_effect = ImportError("No module named 'pymongo'")
        with pytest.raises(ImportError, match=r"dblift\[mongodb\]"):
            manager.create_connection()


def test_get_collection_connects_on_demand():
    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    fake_database = MagicMock()
    fake_client.__getitem__.return_value = fake_database
    with _patch_mongo_client(fake_client):
        manager.get_collection("users")
    fake_database.__getitem__.assert_called_once_with("users")


def test_database_url_is_masked():
    manager = MongoDbConnectionManager(_config(url="mongodb://app:s3cret@localhost:27017"))
    assert "s3cret" not in (manager.get_database_url() or "")


def test_close_releases_the_client():
    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    with _patch_mongo_client(fake_client):
        manager.create_connection()
    manager.close()
    fake_client.close.assert_called_once()
    assert manager.client is None
    assert manager.database is None


def test_close_before_connect_is_a_no_op():
    MongoDbConnectionManager(_config()).close()
