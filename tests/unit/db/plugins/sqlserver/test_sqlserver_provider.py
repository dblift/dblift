"""SQL Server native provider unit tests (no live SQL Server needed)."""

from unittest.mock import MagicMock

from config.dblift_config import DbliftConfig
from db.plugins.sqlserver.provider import SqlServerProvider
from db.sqlalchemy_provider import SqlAlchemyProvider


def _cfg():
    return DbliftConfig.from_dict(
        {
            "database": {
                "type": "sqlserver",
                "host": "localhost",
                "port": 1433,
                "database": "testdb",
                "username": "sa",
                "password": "Password1!",
            }
        }
    )


def test_sqlserver_provider_is_native():
    p = SqlServerProvider(_cfg())
    assert isinstance(p, SqlAlchemyProvider)
    assert not hasattr(p, "jvm_manager")
    assert not hasattr(p, "connection_manager")


def test_sqlserver_provider_has_required_methods():
    p = SqlServerProvider(_cfg())
    for method in (
        "create_schema_if_not_exists",
        "table_exists",
        "get_columns_query",
        "get_add_column_sql",
        "get_parameter_placeholders",
        "get_database_version",
        "acquire_migration_lock",
        "release_migration_lock",
        "create_migration_history_table_if_not_exists",
        "record_migration",
        "get_applied_migrations",
        "clean_schema",
        "get_clean_preview",
        "record_undo",
        "repair_migration_history",
    ):
        assert callable(getattr(p, method, None)), f"missing {method}"


def test_sqlserver_provider_canonical_dialect_key():
    p = SqlServerProvider(_cfg())
    assert p.canonical_dialect_key == "sqlserver"


def test_get_columns_query_returns_parameterized_catalog_query():
    p = SqlServerProvider(_cfg())

    sql, params = p.get_columns_query("d'bo", "users")

    assert "INFORMATION_SCHEMA.COLUMNS" in sql
    assert "TABLE_SCHEMA = ? AND TABLE_NAME = ?" in sql
    assert "d'bo" not in sql
    assert params == ["d'bo", "users"]


def test_get_add_column_sql_quotes_identifiers():
    p = SqlServerProvider(_cfg())

    sql = p.get_add_column_sql("d]bo", "user]s", "new]col", "NVARCHAR(50)")

    assert sql == "ALTER TABLE [d]]bo].[user]]s] ADD [new]]col] NVARCHAR(50)"


def test_get_parameter_placeholders_uses_qmark_style():
    p = SqlServerProvider(_cfg())

    assert p.get_parameter_placeholders(3) == "?, ?, ?"


def test_sqlserver_migration_lock_table_defined():
    assert hasattr(SqlServerProvider, "MIGRATION_LOCK_TABLE")
    assert SqlServerProvider.MIGRATION_LOCK_TABLE == "dblift_migration_lock"


def test_create_migration_lock_table_uses_parameterized_catalog_check():
    provider = object.__new__(SqlServerProvider)
    provider.create_schema_if_not_exists = MagicMock()
    provider.execute_statement = MagicMock()

    provider.create_migration_lock_table_if_not_exists("d'bo")

    provider.create_schema_if_not_exists.assert_called_once_with("d'bo")
    sql = provider.execute_statement.call_args.args[0]
    params = provider.execute_statement.call_args.kwargs["params"]
    assert "s.name = ? AND t.name = ?" in sql
    assert "s.name = '" not in sql
    assert "t.name = '" not in sql
    assert params == ["d'bo", "dblift_migration_lock"]


def test_create_snapshot_table_uses_parameterized_catalog_check():
    provider = object.__new__(SqlServerProvider)
    provider.create_schema_if_not_exists = MagicMock()
    provider.execute_statement = MagicMock()

    provider.create_snapshot_table_if_not_exists("d'bo", "snap's")

    provider.create_schema_if_not_exists.assert_called_once_with("d'bo")
    sql = provider.execute_statement.call_args.args[0]
    params = provider.execute_statement.call_args.kwargs["params"]
    assert "s.name = ? AND t.name = ?" in sql
    assert "s.name = '" not in sql
    assert "t.name = '" not in sql
    assert params == ["d'bo", "snap's"]


def test_execute_statement_creates_schema_when_schema_is_passed(monkeypatch):
    provider = object.__new__(SqlServerProvider)
    provider.create_schema_if_not_exists = MagicMock()
    executed = {}

    def fake_execute_statement(self, sql, schema=None, params=None):
        executed["sql"] = sql
        executed["schema"] = schema
        executed["params"] = params
        return 7

    monkeypatch.setattr(SqlAlchemyProvider, "execute_statement", fake_execute_statement)

    assert provider.execute_statement("CREATE TABLE t(id int)", schema="dbo", params=[1]) == 7
    provider.create_schema_if_not_exists.assert_called_once_with("dbo")
    assert executed == {"sql": "CREATE TABLE t(id int)", "schema": "dbo", "params": [1]}


def test_acquire_migration_lock_uses_session_scoped_application_lock():
    provider = object.__new__(SqlServerProvider)
    provider.execute_query = MagicMock(return_value=[{"lock_result": 0}])

    assert provider.acquire_migration_lock("dbo", wait_timeout_seconds=3) is True

    sql, params = provider.execute_query.call_args.args
    assert "sp_getapplock" in sql
    assert "Session" in sql
    assert params == ["dblift_migration_lock_dbo", 3000]


def test_acquire_migration_lock_accepts_wait_success_code():
    provider = object.__new__(SqlServerProvider)
    provider.execute_query = MagicMock(return_value=[{"lock_result": 1}])

    assert provider.acquire_migration_lock("dbo") is True


def test_release_migration_lock_uses_session_scoped_application_lock():
    provider = object.__new__(SqlServerProvider)
    provider.execute_query = MagicMock(return_value=[{"release_result": 0}])

    assert provider.release_migration_lock("dbo") is True

    sql, params = provider.execute_query.call_args.args
    assert "sp_releaseapplock" in sql
    assert "Session" in sql
    assert params == ["dblift_migration_lock_dbo"]
