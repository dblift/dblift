"""``MongoDbConnectionManager`` — owns the driver handles.

``.client`` and ``.database`` are load-bearing names: MigrationContext.db
and .raw_client resolve against exactly these attributes.
"""

from unittest.mock import MagicMock, patch

import pytest

from config import DbliftConfig
from db.plugins.mongodb.config import MongoDbConfig
from db.plugins.mongodb.mongodb import MongoDbConnectionManager


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


def test_create_connection_sets_both_handles():
    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    fake_database = MagicMock()
    fake_client.__getitem__.return_value = fake_database

    with patch("pymongo.MongoClient", return_value=fake_client) as mongo_client:
        returned = manager.create_connection()

    mongo_client.assert_called_once()
    assert mongo_client.call_args.args[0] == "mongodb://localhost:27017"
    assert manager.client is fake_client
    assert manager.database is fake_database
    assert returned is fake_database


def test_database_is_selected_by_name():
    manager = MongoDbConnectionManager(_config(database="appdb"))
    fake_client = MagicMock()
    with patch("pymongo.MongoClient", return_value=fake_client):
        manager.create_connection()
    fake_client.__getitem__.assert_called_once_with("appdb")


def test_missing_driver_gives_an_install_hint():
    manager = MongoDbConnectionManager(_config())
    with patch("db.plugins.mongodb.mongodb.connection_manager._load_mongo_client") as loader:
        loader.side_effect = ImportError("No module named 'pymongo'")
        with pytest.raises(ImportError, match=r'dblift\[mongodb\]'):
            manager.create_connection()


def test_get_collection_connects_on_demand():
    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    fake_database = MagicMock()
    fake_client.__getitem__.return_value = fake_database
    with patch("pymongo.MongoClient", return_value=fake_client):
        manager.get_collection("users")
    fake_database.__getitem__.assert_called_once_with("users")


def test_database_url_is_masked():
    manager = MongoDbConnectionManager(_config(url="mongodb://app:s3cret@localhost:27017"))
    assert "s3cret" not in (manager.get_database_url() or "")


def test_close_releases_the_client():
    manager = MongoDbConnectionManager(_config())
    fake_client = MagicMock()
    with patch("pymongo.MongoClient", return_value=fake_client):
        manager.create_connection()
    manager.close()
    fake_client.close.assert_called_once()
    assert manager.client is None
    assert manager.database is None


def test_close_before_connect_is_a_no_op():
    MongoDbConnectionManager(_config()).close()
