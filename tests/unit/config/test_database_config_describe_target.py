"""Tests for ``BaseDatabaseConfig.describe_target`` — a one-line, secret-free
summary of a resolved database target, used by ``dblift mcp`` to announce on
stderr what it will connect to. Built on ``to_safe_dict()``, so every shape
here is exercised through the same masking a ``repr()`` would go through.
"""

import pytest

from dblift.config._subclasses.dummy_config import DummyDatabaseConfig
from dblift.config.database_config import BaseDatabaseConfig
from dblift.db.plugins.cosmosdb.config import CosmosDbConfig
from dblift.db.plugins.snowflake.config import SnowflakeConfig


@pytest.mark.unit
def test_describe_target_names_postgresql_fields():
    database = BaseDatabaseConfig.create(
        {
            "type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "username": "dblift_reader",
            "password": "pw2",
        }
    )

    line = database.describe_target()

    assert line == "postgresql dblift_reader@localhost:5432/testdb"
    assert "pw2" not in line


@pytest.mark.unit
def test_describe_target_shows_the_masked_url():
    """A `url`-configured database prints the masked URL alone — the URL's
    own scheme already names the dialect, so it is not repeated."""
    database = BaseDatabaseConfig.create({"url": "postgresql://u:secret@h:5432/db"})

    line = database.describe_target()

    assert line == "postgresql://u:***@h:5432/db"
    assert "secret" not in line


@pytest.mark.unit
def test_describe_target_names_a_snowflake_account_when_host_is_absent():
    """A Snowflake config using `account:` instead of `host:` must not drop
    the account or produce a stray `@/` where the (empty) host would go."""
    database = SnowflakeConfig(
        type="snowflake",
        username="svc_user",
        password="pw",
        account="myaccount",
        database="mydb",
    )

    line = database.describe_target()

    assert line == "snowflake svc_user@myaccount/mydb"
    assert "@/" not in line
    assert "pw" not in line


@pytest.mark.unit
def test_describe_target_names_a_cosmosdb_endpoint_and_database_without_the_key():
    """CosmosDB is addressed by account_endpoint/database_name, not
    host/database; the key must never appear in the line."""
    database = CosmosDbConfig(
        type="cosmosdb",
        account_endpoint="https://my-account.documents.azure.com:443",
        account_key="topsecretkey",
        database_name="mydb",
    )

    line = database.describe_target()

    assert line == "cosmosdb https://my-account.documents.azure.com:443/mydb"
    assert "topsecretkey" not in line


@pytest.mark.unit
def test_describe_target_reports_nothing_configured_when_no_target_field_is_set():
    database = DummyDatabaseConfig(type="dummy")

    assert database.describe_target() == "dummy (no host, account or path configured)"
