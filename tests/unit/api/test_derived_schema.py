"""An omitted schema gets the same dialect default through the CLI and the API.

The CLI used to derive it in ``_validate_db_config`` only, so a Python API
client on Oracle with no ``schema`` quoted an empty identifier
(``CREATE TABLE ""."DBLIFT_SCHEMA_HISTORY"``, ORA-01741) and a MySQL client
expanded ``${dblift_schema}`` to an empty string.
"""

import argparse
import copy
from unittest.mock import MagicMock, patch

import pytest

from dblift.api._client_factory import apply_derived_schema, client_from_config
from dblift.cli._config_helpers import _validate_db_config
from dblift.config import DatabaseConfig, DbliftConfig

pytestmark = pytest.mark.unit

# (dialect config without a schema, schema the CLI targets)
CASES = {
    "oracle": (
        dict(
            type="oracle",
            url="oracle+oracledb://localhost:1521/?service_name=FREEPDB1",
            username="app_user",
            password="pw",
        ),
        "APP_USER",
    ),
    "mysql": (
        dict(
            type="mysql",
            url="mysql+pymysql://localhost:3306/appdb",
            username="root",
            password="pw",
        ),
        "appdb",
    ),
    "mariadb": (
        dict(
            type="mariadb",
            url="mariadb+pymysql://localhost:3306/appdb",
            username="root",
            password="pw",
        ),
        "appdb",
    ),
    "sqlserver": (
        dict(
            type="sqlserver",
            url="mssql+pymssql://localhost:1433/appdb",
            username="sa",
            password="pw",
        ),
        "dbo",
    ),
    "postgresql": (
        dict(
            type="postgresql",
            url="postgresql+psycopg://localhost:5432/appdb",
            username="postgres",
            password="pw",
        ),
        "public",
    ),
    "sqlite": (dict(type="sqlite", url="sqlite:///app.db"), "main"),
    "duckdb": (dict(type="duckdb", url="duckdb:///app.duckdb"), "main"),
}


def _config(kwargs, **extra):
    return DatabaseConfig(**{**kwargs, **extra})


@pytest.mark.parametrize("dialect", sorted(CASES))
def test_omitted_schema_gets_dialect_default(dialect):
    kwargs, expected = CASES[dialect]
    database = _config(kwargs)
    apply_derived_schema(database)
    assert database.schema == expected


@pytest.mark.parametrize("dialect", ["oracle", "mysql", "sqlserver"])
@pytest.mark.parametrize("empty", ["", None])
def test_empty_or_null_schema_is_derived(dialect, empty):
    kwargs, expected = CASES[dialect]
    database = _config(kwargs, schema=empty)
    apply_derived_schema(database)
    assert database.schema == expected


@pytest.mark.parametrize("dialect", sorted(CASES))
def test_configured_schema_is_kept(dialect):
    kwargs, _ = CASES[dialect]
    database = _config(kwargs, schema="CONFIGURED" if dialect == "oracle" else "configured")
    apply_derived_schema(database)
    assert database.schema in ("CONFIGURED", "configured")


def test_mysql_without_database_keeps_an_empty_schema():
    database = _config(
        dict(type="mysql", url="mysql+pymysql://localhost:3306/", username="u", password="p")
    )
    apply_derived_schema(database)
    assert not database.schema


def test_db2_has_no_derived_schema():
    database = _config(
        dict(type="db2", url="db2+ibm_db://localhost:50000/testdb", username="u", password="p")
    )
    apply_derived_schema(database)
    assert not database.schema


def _cli_schema(database):
    """Schema the CLI validation step leaves on *database*."""
    config = MagicMock()
    config.database = database
    parser = MagicMock(spec=argparse.ArgumentParser)
    parser.error.side_effect = SystemExit(2)
    args = argparse.Namespace(command="migrate", database_url=None)
    try:
        _validate_db_config(args, config, parser, ["migrate"])
    except SystemExit:
        pass
    return database.schema


def _api_schema(database):
    """Schema the API client factory hands to the provider for *database*."""
    captured = {}

    def fake_create_provider(config, _log):
        captured["schema"] = config.database.schema
        raise RuntimeError("stop before connecting")

    with patch(
        "dblift.api._client_factory.ProviderRegistry.create_provider",
        side_effect=fake_create_provider,
    ):
        with pytest.raises(RuntimeError, match="stop before connecting"):
            client_from_config(DbliftConfig(database=database), logger=MagicMock())
    return captured["schema"]


@pytest.mark.parametrize("dialect", sorted(CASES) + ["db2"])
def test_api_and_cli_target_the_same_schema(dialect):
    if dialect == "db2":
        kwargs = dict(
            type="db2", url="db2+ibm_db://localhost:50000/testdb", username="u", password="p"
        )
    else:
        kwargs, _ = CASES[dialect]
    database = _config(kwargs)
    assert _api_schema(copy.deepcopy(database)) == _cli_schema(copy.deepcopy(database))


def test_api_factory_does_not_mutate_the_callers_config():
    kwargs, _ = CASES["oracle"]
    config = DbliftConfig(database=_config(kwargs))
    with patch(
        "dblift.api._client_factory.ProviderRegistry.create_provider",
        side_effect=RuntimeError("stop"),
    ):
        with pytest.raises(RuntimeError):
            client_from_config(config, logger=MagicMock())
    assert config.database.schema == ""
