"""Tests for data history/change-set table creation."""

import pytest

from db.base_provider import BaseProvider
from db.base_quirks import BaseQuirks
from db.provider_registry import ProviderRegistry


class _ExistingHistoryProvider:
    quirks = BaseQuirks()

    def __init__(self) -> None:
        self.statements = []

    def get_schema_qualified_name(self, schema: str, table_name: str) -> str:
        return f"{schema}.{table_name}" if schema else table_name

    def get_normalized_object_name(self, table_name: str) -> str:
        return table_name

    def table_exists(self, schema: str, table_name: str) -> bool:
        return True

    def get_columns_query(self, schema: str, table_name: str):
        return "SELECT column_name FROM columns", [schema, table_name]

    def execute_query(self, sql: str, params=None):
        return [{"column_name": "id"}, {"column_name": "sql_checksum"}]

    def get_add_column_sql(self, schema: str, table_name: str, column: str, type_def: str) -> str:
        return f"ALTER TABLE {schema}.{table_name} ADD {column} {type_def}"

    def execute_statement(self, sql: str, params=None):
        self.statements.append(sql)
        return 1

    def commit_transaction(self) -> None:
        self.statements.append("COMMIT")


class _AlreadyExistsQuirks(BaseQuirks):
    def is_data_history_table_already_exists_error(self, error_message: str) -> bool:
        return "already exists" in error_message


class _AlreadyExistsHistoryProvider(_ExistingHistoryProvider):
    quirks = _AlreadyExistsQuirks()

    def table_exists(self, schema: str, table_name: str) -> bool:
        return False

    def execute_statement(self, sql: str, params=None):
        if sql.startswith("CREATE TABLE"):
            raise RuntimeError("table already exists")
        self.statements.append(sql)
        return 1


def test_existing_data_history_table_is_left_unchanged():
    provider = _ExistingHistoryProvider()

    BaseProvider._create_data_table_if_not_exists(
        provider,
        "public",
        "dblift_data_history_corrections",
        kind="history",
    )

    assert provider.statements == []


def test_existing_data_change_set_table_is_left_unchanged():
    provider = _ExistingHistoryProvider()

    BaseProvider._create_data_table_if_not_exists(
        provider,
        "public",
        "dblift_data_change_set",
        kind="change_set",
    )

    assert provider.statements == []


def test_data_change_set_table_ddl_includes_dataset_column():
    ddl = BaseQuirks().build_data_change_set_table_ddl("dblift_data_change_set")

    assert "dataset VARCHAR(100)" in ddl
    assert "history_id" in ddl


class _OracleLikeHistoryProvider(_ExistingHistoryProvider):
    """Mimics Oracle: unquoted identifiers fold uppercase, names are quoted."""

    def get_normalized_object_name(self, table_name: str) -> str:
        return table_name.upper()

    def get_schema_qualified_name(self, schema: str, table_name: str) -> str:
        return f'"{schema}"."{table_name}"'

    def table_exists(self, schema: str, table_name: str) -> bool:
        return False


def test_data_table_create_uses_dialect_normalized_name():
    # The CREATE must qualify the dialect-normalized name (upper-case on Oracle),
    # matching the existence check, so the data table lands where reads/writes and
    # table_exists look for it — like the migration history table.
    provider = _OracleLikeHistoryProvider()

    BaseProvider._create_data_table_if_not_exists(
        provider,
        "DBLIFT_TEST",
        "dblift_data_history_corrections",
        kind="history",
    )

    creates = [s for s in provider.statements if s.startswith("CREATE TABLE")]
    assert creates, "expected a CREATE TABLE statement"
    assert '"DBLIFT_TEST"."DBLIFT_DATA_HISTORY_CORRECTIONS"' in creates[0]
    assert "dblift_data_history_corrections" not in creates[0]


def test_already_exists_data_history_table_error_is_treated_as_existing():
    provider = _AlreadyExistsHistoryProvider()

    BaseProvider._create_data_table_if_not_exists(
        provider,
        "public",
        "dblift_data_history_corrections",
        kind="history",
    )

    assert provider.statements == []


# Per-dialect portable DDL: the generic base types (TEXT, TIMESTAMP DEFAULT
# CURRENT_TIMESTAMP) only work on PG/MySQL/SQLite. SQL Server (TIMESTAMP =
# rowversion), Oracle and DB2 (no TEXT type) need dialect-correct types.
@pytest.mark.parametrize(
    "dialect, text_type, ts_fragment",
    [
        ("postgresql", "TEXT", "installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("mysql", "TEXT", "installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("sqlite", "TEXT", "installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("sqlserver", "VARCHAR(MAX)", "installed_on DATETIME2 DEFAULT GETDATE()"),
        ("oracle", "CLOB", "installed_on TIMESTAMP DEFAULT SYSTIMESTAMP"),
        ("db2", "CLOB", "installed_on TIMESTAMP DEFAULT CURRENT TIMESTAMP"),
    ],
)
def test_data_history_ddl_uses_portable_types_per_dialect(dialect, text_type, ts_fragment):
    ddl = ProviderRegistry.get_quirks(dialect).build_data_history_table_ddl("H", 100, 128)
    assert ts_fragment in ddl
    assert f"summary {text_type}" in ddl
    assert f"note {text_type}" in ddl
    if text_type != "TEXT":
        # dialects without a TEXT type must not emit one
        assert "TEXT" not in ddl
    if dialect == "sqlserver":
        # bare TIMESTAMP defaults fail on tsql (TIMESTAMP == rowversion)
        assert "TIMESTAMP DEFAULT" not in ddl


# Idempotent create: dialects without ``CREATE TABLE IF NOT EXISTS`` raise on a
# re-create; the data-table create must recognise that as "already exists" so the
# ledger create stays idempotent (Oracle in particular: the data table is a
# quoted lower-case identifier that table_exists can miss).
@pytest.mark.parametrize(
    "dialect, already_exists_msg, other_msg",
    [
        (
            "oracle",
            "ORA-00955: name is already used by an existing object",
            "ORA-00942: table or view does not exist",
        ),
        (
            "sqlserver",
            "There is already an object named 'x' in the database.",
            "Invalid object name 'x'.",
        ),
        (
            "db2",
            "SQL0601N  ... is identical to the existing name ... SQLSTATE=42710",
            "SQL0204N ... SQLSTATE=42704",
        ),
    ],
)
def test_data_table_already_exists_error_is_detected_per_dialect(
    dialect, already_exists_msg, other_msg
):
    quirks = ProviderRegistry.get_quirks(dialect)
    assert quirks.is_data_history_table_already_exists_error(already_exists_msg)
    assert quirks.is_data_change_set_table_already_exists_error(already_exists_msg)
    assert not quirks.is_data_history_table_already_exists_error(other_msg)
    assert not quirks.is_data_change_set_table_already_exists_error(other_msg)


@pytest.mark.parametrize(
    "dialect, blob_type",
    [
        ("postgresql", "TEXT"),
        ("mysql", "LONGTEXT"),
        ("sqlite", "TEXT"),
        ("sqlserver", "VARCHAR(MAX)"),
        ("oracle", "CLOB"),
        ("db2", "CLOB"),
    ],
)
def test_data_change_set_ddl_model_data_uses_portable_text_type(dialect, blob_type):
    ddl = ProviderRegistry.get_quirks(dialect).build_data_change_set_table_ddl("C", 64, 128)
    assert f"model_data {blob_type} NOT NULL" in ddl
    if dialect in ("oracle", "db2", "sqlserver"):
        # dialects without a TEXT type must not emit one
        assert "TEXT" not in ddl


def test_data_change_set_table_ddl_has_composite_primary_key():
    ddl = BaseQuirks().build_data_change_set_table_ddl("dblift_data_change_set")
    assert "PRIMARY KEY (dataset, history_id)" in ddl
    assert "dataset VARCHAR(100) NOT NULL" in ddl
    assert "history_id VARCHAR(100) NOT NULL" in ddl


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite", "sqlserver", "oracle", "db2"])
def test_data_change_set_ddl_has_pk_per_dialect(dialect):
    ddl = ProviderRegistry.get_quirks(dialect).build_data_change_set_table_ddl("C", 64, 128)
    assert "PRIMARY KEY (dataset, history_id)" in ddl


def test_data_audit_table_ddl_has_chain_columns_and_pk():
    ddl = BaseQuirks().build_data_audit_table_ddl("dblift_data_audit")
    for fragment in (
        "seq INTEGER NOT NULL",
        "event VARCHAR(20) NOT NULL",
        "prev_hash VARCHAR(64) NOT NULL",
        "row_hash VARCHAR(64) NOT NULL",
        "PRIMARY KEY (dataset, seq)",
    ):
        assert fragment in ddl


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite", "sqlserver", "oracle", "db2"])
def test_data_audit_ddl_has_pk_per_dialect(dialect):
    ddl = ProviderRegistry.get_quirks(dialect).build_data_audit_table_ddl("A", 100, 128)
    assert "PRIMARY KEY (dataset, seq)" in ddl
    assert "row_hash VARCHAR(64) NOT NULL" in ddl
