"""DB2 quirks behavior."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.sql_generator.sql_statement import SqlStatement
from dblift.db.plugins.db2.quirks import Db2Quirks


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


# ``build_retry_drop_strategies`` builds the DROP targets to try, in order,
# after a CREATE TABLE failed because the table is already there but the
# original DROP could not find it. DB2 folds unquoted identifiers to upper
# case in SYSCAT, so the name the caller holds and the name the catalog
# stores can differ.


def _lookup_executor(rows=None, error=None):
    """Query executor stub, shaped like the call the lookup actually makes.

    ``execute_query(connection, sql, params)`` — three positional arguments,
    with four bound parameters, returning a list of row mappings.
    """
    query_executor = MagicMock()
    if error is not None:
        query_executor.execute_query.side_effect = error
    else:
        query_executor.execute_query.return_value = rows
    return query_executor


@pytest.mark.parametrize("rows", [[], None], ids=["no_rows", "no_result"])
def test_db2_retry_drop_strategies_stand_on_the_names_passed_in(rows):
    """No catalog match: the quoted form of the caller's names is all there is."""
    connection = object()
    query_executor = _lookup_executor(rows=rows)

    strategies = Db2Quirks().build_retry_drop_strategies(
        query_executor, connection, "APP", "ORDERS"
    )

    assert strategies == ['"APP"."ORDERS"']
    connection_arg, _sql, params = query_executor.execute_query.call_args.args
    # The lookup runs on the connection it was handed, not one of its own,
    # and the names go in as bound parameters rather than inlined text.
    assert connection_arg is connection
    assert params == ["APP", "APP", "ORDERS", "ORDERS"]


@pytest.mark.parametrize(
    "row",
    [
        {"TABSCHEMA": "APP", "TABNAME": "ORDERS"},
        {"tabschema": "APP", "tabname": "ORDERS"},
    ],
    ids=["upper_case_keys", "lower_case_keys"],
)
def test_db2_retry_drop_tries_the_catalog_name_first(row):
    """The upper-cased name SYSCAT stores is the one a DROP has to target.

    It is prepended, not appended: trying the caller's lower-case form first
    would fail again for the same reason the first DROP did.
    """
    strategies = Db2Quirks().build_retry_drop_strategies(
        _lookup_executor(rows=[row]), object(), "app", "orders"
    )

    assert strategies == ['"APP"."ORDERS"', '"app"."orders"']


def test_db2_retry_drop_tries_a_different_schema_first():
    """The schema SYSCAT reports wins over the one the caller assumed."""
    strategies = Db2Quirks().build_retry_drop_strategies(
        _lookup_executor(rows=[{"TABSCHEMA": "DB2INST1", "TABNAME": "ORDERS"}]),
        object(),
        "APP",
        "ORDERS",
    )

    assert strategies == ['"DB2INST1"."ORDERS"', '"APP"."ORDERS"']


def test_db2_retry_drop_lookup_strips_quotes_from_the_bound_names():
    """SYSCAT holds bare identifiers, so a quoted name must not be matched
    against a value that still carries its quotes."""
    query_executor = _lookup_executor(rows=[])

    Db2Quirks().build_retry_drop_strategies(query_executor, object(), '"APP"', '"ORDERS"')

    assert query_executor.execute_query.call_args.args[2] == [
        "APP",
        "APP",
        "ORDERS",
        "ORDERS",
    ]


def test_db2_retry_drop_strategies_survive_a_failing_lookup():
    """The catalog query is best-effort — the caller still gets its list.

    Letting the failure out would turn a retry that might have worked into a
    hard error, on a path only reached because something already went wrong.
    """
    query_executor = _lookup_executor(error=RuntimeError("SQL0204N SYSCAT.TABLES"))

    strategies = Db2Quirks().build_retry_drop_strategies(query_executor, object(), "APP", "ORDERS")

    assert strategies == ['"APP"."ORDERS"']


def test_db2_retry_drop_lookup_failure_logs_under_this_modules_own_logger(caplog):
    """The swallowed failure is attributed to the module that emits it.

    A logger named for some other namespace sends the only trace of this
    failure somewhere the reader of this file has no reason to look.
    """
    query_executor = _lookup_executor(error=RuntimeError("catalog unavailable"))

    with caplog.at_level(logging.DEBUG):
        Db2Quirks().build_retry_drop_strategies(query_executor, object(), "APP", "ORDERS")

    emitters = {
        record.name for record in caplog.records if "catalog unavailable" in record.getMessage()
    }
    assert emitters == {"dblift.db.plugins.db2.quirks"}
