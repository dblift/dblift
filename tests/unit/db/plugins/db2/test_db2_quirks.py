"""DB2 quirks behavior."""

from types import SimpleNamespace

import pytest

from core.sql_generator.sql_statement import SqlStatement
from db.plugins.db2.quirks import Db2Quirks


def test_build_snapshot_table_ddl_refuses_db2_snapshot_ddl() -> None:
    with pytest.raises(NotImplementedError):
        Db2Quirks().build_snapshot_table_ddl('"APP"."DBLIFT_SCHEMA_SNAPSHOTS"', 255, 128)


def test_build_data_history_table_ddl_declares_id_not_null() -> None:
    # DB2 rejects a PRIMARY KEY column without an explicit NOT NULL
    # (SQL0542N) — unlike PG/MySQL/SQLite, where PRIMARY KEY implies it.
    ddl = Db2Quirks().build_data_history_table_ddl('"APP"."DBLIFT_DATA_HISTORY"', 100, 128)
    assert "id VARCHAR(100) NOT NULL PRIMARY KEY" in ddl


# Issue #910: diff --generate-sql produced zero statements for a DB2
# nullable-change or type-change drift because Db2Quirks never overrode
# render_column_nullable_change / render_column_type_change and fell back
# to BaseQuirks's "return None" default.


def test_render_column_nullable_change_sets_not_null() -> None:
    # expected_nullable=False -> drift must be closed with SET NOT NULL.
    col_diff = SimpleNamespace(nullable_diff=(False, True))
    stmt = Db2Quirks().render_column_nullable_change(col_diff, "ORDERS", "EMAIL", "db2")

    assert isinstance(stmt, SqlStatement)
    assert stmt.sql == "ALTER TABLE ORDERS ALTER COLUMN EMAIL SET NOT NULL;"
    assert stmt.statement_type == "ALTER"
    assert stmt.object_type == "COLUMN"
    assert stmt.object_name == "ORDERS.EMAIL"
    assert stmt.dialect == "db2"
    # A NOT-NULL-violating row must fail the migration before the ALTER runs.
    assert stmt.pre_check == "SELECT COUNT(*) FROM ORDERS WHERE EMAIL IS NULL;"
    assert stmt.error_if_check_fails is True


def test_render_column_nullable_change_drops_not_null() -> None:
    # expected_nullable=True -> drift must be closed with DROP NOT NULL.
    col_diff = SimpleNamespace(nullable_diff=(True, False))
    stmt = Db2Quirks().render_column_nullable_change(col_diff, "ORDERS", "EMAIL", "db2")

    assert isinstance(stmt, SqlStatement)
    assert stmt.sql == "ALTER TABLE ORDERS ALTER COLUMN EMAIL DROP NOT NULL;"
    assert stmt.pre_check is None


def test_render_column_nullable_change_returns_none_without_a_diff() -> None:
    col_diff = SimpleNamespace(nullable_diff=None)
    assert Db2Quirks().render_column_nullable_change(col_diff, "ORDERS", "EMAIL", "db2") is None


def test_render_column_type_change_sets_data_type() -> None:
    col_diff = SimpleNamespace(data_type_diff=("VARCHAR(100)", "VARCHAR(50)"))
    stmt = Db2Quirks().render_column_type_change(col_diff, "ORDERS", "STATUS", "db2")

    assert isinstance(stmt, SqlStatement)
    assert stmt.sql == "ALTER TABLE ORDERS ALTER COLUMN STATUS SET DATA TYPE VARCHAR(100);"
    assert stmt.statement_type == "ALTER"
    assert stmt.object_type == "COLUMN"
    assert stmt.object_name == "ORDERS.STATUS"
    assert stmt.dialect == "db2"


def test_render_column_type_change_returns_none_without_a_diff() -> None:
    col_diff = SimpleNamespace(data_type_diff=None)
    assert Db2Quirks().render_column_type_change(col_diff, "ORDERS", "STATUS", "db2") is None
