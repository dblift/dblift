"""Unit tests for :class:`db.plugins.mysql.provider.MySqlProvider`."""

from unittest.mock import MagicMock

import db.plugins.mysql.provider as mysql_provider_module
import db.sqlalchemy_provider as sqlalchemy_provider_module
from db.plugins.mysql.provider import MySqlProvider, _quote_identifier


class _Provider(MySqlProvider):
    def __init__(self):
        self.queries = []
        self.statements = []
        self.query_results: dict = {}
        self.table_exists_value = True
        self.log = MagicMock()
        self.query_executor = MagicMock()
        self._fake_connection = MagicMock()

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        return 1

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        for key, rows in self.query_results.items():
            if key in sql:
                return rows
        return []

    def table_exists(self, schema, table_name):
        return self.table_exists_value

    def _ensure_connection(self):
        return self._fake_connection


def test_quote_identifier_escapes_backticks():
    assert _quote_identifier("a`b") == "`a``b`"


def test_execute_statement_with_schema_prepares_database(monkeypatch):
    provider = _Provider()
    calls = []
    monkeypatch.setattr(
        provider, "create_schema_if_not_exists", lambda s: calls.append(("create", s))
    )
    monkeypatch.setattr(provider, "set_current_schema", lambda s: calls.append(("use", s)))
    monkeypatch.setattr(
        sqlalchemy_provider_module.SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: 1,
    )

    result = MySqlProvider.execute_statement(provider, "SELECT 1", schema="mydb")

    assert calls == [("create", "mydb"), ("use", "mydb")]
    assert result == 1


def test_execute_statement_without_schema_skips_prep(monkeypatch):
    provider = _Provider()
    create = MagicMock()
    monkeypatch.setattr(provider, "create_schema_if_not_exists", create)
    monkeypatch.setattr(
        sqlalchemy_provider_module.SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: 1,
    )

    MySqlProvider.execute_statement(provider, "SELECT 1")

    create.assert_not_called()


def test_create_schema_if_not_exists_skips_when_present():
    provider = _Provider()
    provider.query_results["SCHEMA_NAME"] = [{"SCHEMA_NAME": "mydb"}]

    provider.create_schema_if_not_exists("mydb")

    assert provider.statements == []


def test_create_schema_if_not_exists_creates_when_missing():
    provider = _Provider()
    provider.query_results["SCHEMA_NAME"] = []

    provider.create_schema_if_not_exists("mydb")

    assert "CREATE DATABASE IF NOT EXISTS `mydb`" in provider.statements[0][0]


def test_table_exists_true_and_false():
    provider = _Provider()
    provider.query_results["information_schema.TABLES"] = [{"TABLE_NAME": "orders"}]
    assert MySqlProvider.table_exists(provider, "mydb", "orders") is True

    provider.query_results["information_schema.TABLES"] = []
    assert MySqlProvider.table_exists(provider, "mydb", "orders") is False


def test_get_database_version_with_rows():
    provider = _Provider()
    provider.query_results["VERSION()"] = [{"version": "8.0.34"}]

    assert provider.get_database_version() == "MySQL 8.0.34"


def test_get_database_version_without_rows():
    provider = _Provider()

    assert provider.get_database_version() == "MySQL Unknown Version"


def test_supports_transactional_ddl_is_false():
    provider = _Provider()
    assert provider.supports_transactional_ddl() is False


def test_set_current_schema_executes_use_statement(monkeypatch):
    provider = _Provider()
    captured = {}

    def _fake_execute_statement(self, sql, schema=None, params=None):
        captured["sql"] = sql
        return 1

    monkeypatch.setattr(
        sqlalchemy_provider_module.SqlAlchemyProvider, "execute_statement", _fake_execute_statement
    )

    MySqlProvider.set_current_schema(provider, "mydb")

    assert captured["sql"] == "USE `mydb`"


def test_get_schema_qualified_name():
    provider = _Provider()
    assert provider.get_schema_qualified_name("mydb", "orders") == "`mydb`.`orders`"


def test_clean_schema_delegates_to_schema_operations(monkeypatch):
    provider = _Provider()
    mock_ops = MagicMock()
    mock_ops.clean_schema.return_value = "summary"
    mock_ops_class = MagicMock(return_value=mock_ops)
    monkeypatch.setattr(mysql_provider_module, "MySqlSchemaOperations", mock_ops_class)

    result = provider.clean_schema("mydb")

    assert result == "summary"
    mock_ops_class.assert_called_once_with(provider.query_executor, provider.log)
    mock_ops.clean_schema.assert_called_once_with(provider._fake_connection, "mydb")


def test_get_clean_preview_delegates_to_schema_operations(monkeypatch):
    provider = _Provider()
    mock_ops = MagicMock()
    mock_ops.get_clean_preview.return_value = "preview"
    mock_ops_class = MagicMock(return_value=mock_ops)
    monkeypatch.setattr(mysql_provider_module, "MySqlSchemaOperations", mock_ops_class)

    result = provider.get_clean_preview("mydb")

    assert result == "preview"
    mock_ops.get_clean_preview.assert_called_once_with(provider._fake_connection, "mydb")


def test_create_migration_lock_table_if_not_exists():
    provider = _Provider()

    provider.create_migration_lock_table_if_not_exists("mydb")

    sql = provider.statements[-1][0]
    assert "dblift_migration_lock" in sql
    assert "ENGINE=InnoDB" in sql


def test_acquire_migration_lock_success_and_failure():
    provider = _Provider()
    provider.query_results["GET_LOCK"] = [{"lock_result": 1}]
    assert provider.acquire_migration_lock("mydb") is True

    provider.query_results["GET_LOCK"] = [{"lock_result": 0}]
    assert provider.acquire_migration_lock("mydb") is False

    provider.query_results["GET_LOCK"] = []
    assert provider.acquire_migration_lock("mydb") is False


def test_release_migration_lock_success_and_failure():
    provider = _Provider()
    provider.query_results["RELEASE_LOCK"] = [{"lock_result": 1}]
    assert provider.release_migration_lock("mydb") is True

    provider.query_results["RELEASE_LOCK"] = [{"lock_result": 0}]
    assert provider.release_migration_lock("mydb") is False


def test_create_migration_history_table_if_not_exists_creates_when_missing():
    provider = _Provider()
    provider.table_exists_value = False

    provider.create_migration_history_table_if_not_exists("mydb")

    assert any("CREATE TABLE" in s[0] for s in provider.statements)


def test_create_migration_history_table_if_not_exists_skips_when_present():
    provider = _Provider()
    provider.table_exists_value = True

    provider.create_migration_history_table_if_not_exists("mydb")

    assert provider.statements == []


def test_create_migration_history_table_with_create_schema_runs_baseline_check():
    provider = _Provider()
    provider.table_exists_value = True
    provider.query_results["SCHEMA_NAME"] = [{"SCHEMA_NAME": "mydb"}]
    provider.query_results["COUNT(1)"] = [{"count": 0}]

    provider.create_migration_history_table_if_not_exists("mydb", create_schema=True)

    assert provider.statements == []


def test_check_baseline_safety_raises_when_history_present():
    provider = _Provider()
    provider.query_results["COUNT(1)"] = [{"count": 3}]

    try:
        provider._check_baseline_safety("mydb", "dblift_schema_history")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "3 migration(s)" in str(exc)


def test_check_baseline_safety_passes_with_empty_history():
    provider = _Provider()
    provider.query_results["COUNT(1)"] = [{"count": 0}]

    provider._check_baseline_safety("mydb", "dblift_schema_history")  # no exception


def test_create_snapshot_table_if_not_exists():
    provider = _Provider()

    provider.create_snapshot_table_if_not_exists("mydb")

    sql = provider.statements[-1][0]
    assert "dblift_schema_snapshots" in sql
    assert "ENGINE=InnoDB" in sql


def test_get_applied_migrations_no_table():
    provider = _Provider()
    provider.table_exists_value = False

    assert provider.get_applied_migrations("mydb") == []


def test_get_applied_migrations_converts_success_to_bool():
    provider = _Provider()
    provider.table_exists_value = True
    provider.query_results["ORDER BY installed_rank"] = [
        {"script": "V1.sql", "success": 1},
        {"script": "V2.sql", "success": None},
    ]

    rows = provider.get_applied_migrations("mydb")

    assert rows[0]["success"] is True
    assert rows[1]["success"] is None


def test_record_migration_inserts_row():
    provider = _Provider()
    provider.table_exists_value = True

    provider.record_migration(
        "mydb",
        {
            "version": "1",
            "description": "init",
            "type": "SQL",
            "script": "V1.sql",
            "checksum": 123,
            "installed_by": "tester",
            "execution_time": 5,
            "success": True,
        },
    )

    sql, _schema, params = provider.statements[-1]
    assert "INSERT INTO" in sql
    assert params[0] == "1"
    assert params[-1] is True


def test_record_undo_records_synthetic_undo_migration():
    provider = _Provider()
    provider.table_exists_value = True

    assert provider.record_undo("mydb", "1", script_name="U1__undo.sql") is True

    sql, _schema, params = provider.statements[-1]
    assert "INSERT INTO" in sql
    assert params[2] == "UNDO_SQL"
    assert params[3] == "U1__undo.sql"


def test_record_undo_default_script_name():
    provider = _Provider()
    provider.table_exists_value = True

    provider.record_undo("mydb", "2")

    sql, _schema, params = provider.statements[-1]
    assert params[3] == "UNDO_2.sql"


def test_repair_migration_history_no_table():
    provider = _Provider()
    provider.table_exists_value = False

    assert provider.repair_migration_history("mydb", "V1.sql", 123) is False


def test_repair_migration_history_updates_row():
    provider = _Provider()
    provider.table_exists_value = True

    class _ProviderWithRows(_Provider):
        def execute_statement(self, sql, schema=None, params=None):
            self.statements.append((sql, schema, params))
            return 1

    provider = _ProviderWithRows()
    provider.table_exists_value = True

    result = provider.repair_migration_history("mydb", "V1.sql", 999, success_value=True)

    assert result is True
    sql, _schema, params = provider.statements[-1]
    assert "UPDATE" in sql
    assert params == [999, True, "V1.sql"]


def test_get_columns_query_contains_schema_and_table():
    provider = _Provider()

    sql = provider.get_columns_query("mydb", "orders")

    assert "mydb" in sql
    assert "orders" in sql


def test_get_add_column_sql():
    provider = _Provider()

    sql = provider.get_add_column_sql("mydb", "orders", "amount", "DECIMAL(10,2)")

    assert sql == "ALTER TABLE `mydb`.`orders` ADD COLUMN `amount` DECIMAL(10,2)"


def test_get_parameter_placeholders():
    provider = _Provider()
    assert provider.get_parameter_placeholders(3) == "?, ?, ?"


def test_is_connection_error():
    provider = _Provider()
    assert provider.is_connection_error(Exception("Connection refused")) is True
    assert provider.is_connection_error(Exception("syntax error")) is False


def test_is_duplicate_object_error():
    provider = _Provider()
    assert provider.is_duplicate_object_error(Exception("Table 'orders' already exists")) is True
    assert provider.is_duplicate_object_error(Exception("Duplicate entry")) is True
    assert provider.is_duplicate_object_error(Exception("syntax error")) is False


def test_is_object_not_found_error():
    provider = _Provider()
    assert provider.is_object_not_found_error(Exception("Table doesn't exist")) is True
    assert provider.is_object_not_found_error(Exception("Unknown table 'orders'")) is True
    assert provider.is_object_not_found_error(Exception("syntax error")) is False


def test_is_permission_error():
    provider = _Provider()
    assert provider.is_permission_error(Exception("Access denied for user")) is True
    assert provider.is_permission_error(Exception("permission denied")) is True
    assert provider.is_permission_error(Exception("syntax error")) is False
