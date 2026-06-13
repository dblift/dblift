"""Regression tests for CosmosDB config loading without SQL Server defaults."""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import Mock, patch

import pytest

from api.client import DBLiftClient
from config.database_config import CosmosDbConfig
from config.dblift_config import load_config


@pytest.mark.unit
def test_env_only_cosmosdb_creates_cosmos_config(monkeypatch):
    import os

    for key in list(os.environ):
        if key.startswith("DBLIFT_DB_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DBLIFT_DB_TYPE", "cosmosdb")
    monkeypatch.setenv("DBLIFT_DB_ACCOUNT_ENDPOINT", "http://localhost:8081/")
    monkeypatch.setenv("DBLIFT_DB_ACCOUNT_KEY", "secret")
    monkeypatch.setenv("DBLIFT_DB_DATABASE", "dblift_test")

    config = load_config(None, Namespace())

    assert isinstance(config.database, CosmosDbConfig)
    assert config.database.account_endpoint == "http://localhost:8081/"
    assert config.database.database_name == "dblift_test"


@pytest.mark.unit
def test_from_config_file_cosmosdb_with_migrations_dir_creates_cosmos_config(tmp_path):
    config_file = tmp_path / "dblift_cosmosdb.yaml"
    config_file.write_text(
        """
database:
  type: cosmosdb
  account_endpoint: http://localhost:8081/
  account_key: secret
  database: dblift_test
""",
        encoding="utf-8",
    )

    provider = Mock()
    with patch("db.provider_registry.ProviderRegistry.create_provider", return_value=provider):
        client = DBLiftClient.from_config_file(str(config_file), migrations_dir=tmp_path / "m")

    assert isinstance(client.config.database, CosmosDbConfig)
    assert client.config.database.database_name == "dblift_test"
