"""Oracle quirks behavior."""

import logging
from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.oracle.quirks import OracleQuirks


def test_build_snapshot_table_ddl_is_not_owned_by_oracle_plugin() -> None:
    with pytest.raises(NotImplementedError):
        OracleQuirks().build_snapshot_table_ddl('"APP"."DBLIFT_SCHEMA_SNAPSHOTS"', 255, 128)


def test_oracle_compat_snapshot_ddl_is_clob_plain_create():
    from dblift.db.plugins.oracle.quirks import OracleQuirks

    ddl = OracleQuirks().build_provider_compat_snapshot_ddl("S.SNAP", 100, 128)
    assert ddl == (
        "CREATE TABLE S.SNAP ("
        "SNAPSHOT_ID VARCHAR2(100) PRIMARY KEY, "
        "CAPTURED_AT VARCHAR2(100) NOT NULL, "
        "CHECKSUM VARCHAR2(128) NOT NULL, "
        "MODEL_DATA CLOB NOT NULL)"
    )


def test_oracle_does_not_skip_existence_check():
    from dblift.db.plugins.oracle.quirks import OracleQuirks

    assert OracleQuirks().provider_compat_snapshot_skips_existence_check is False


def test_oracle_round_trip_drop_table_sql_uses_native_if_exists():
    """23ai+/19.28+ native syntax replaces the old PL/SQL exception wrapper."""
    sql = OracleQuirks().render_round_trip_drop_table_sql('"HR"."EMPLOYEES"')
    assert sql == 'DROP TABLE IF EXISTS "HR"."EMPLOYEES" CASCADE CONSTRAINTS'
    assert "EXECUTE IMMEDIATE" not in sql
    assert "EXCEPTION" not in sql


@pytest.mark.parametrize(
    "obj_type, expected",
    [
        ("TABLE", 'DROP TABLE IF EXISTS "S"."T" CASCADE CONSTRAINTS'),
        ("VIEW", 'DROP VIEW IF EXISTS "S"."T"'),
        ("MATERIALIZED_VIEW", 'DROP MATERIALIZED VIEW IF EXISTS "S"."T"'),
        ("INDEX", 'DROP INDEX IF EXISTS "S"."T"'),
        ("SEQUENCE", 'DROP SEQUENCE IF EXISTS "S"."T"'),
        ("PROCEDURE", 'DROP PROCEDURE IF EXISTS "S"."T"'),
        ("FUNCTION", 'DROP FUNCTION IF EXISTS "S"."T"'),
        ("TRIGGER", 'DROP TRIGGER IF EXISTS "S"."T"'),
    ],
)
def test_oracle_render_drop_for_object_uses_native_if_exists(obj_type, expected):
    result = OracleQuirks().render_drop_for_object(obj_type, '"T"', '"S".', None)
    assert result == expected


# ``build_retry_drop_strategies`` builds the DROP targets to try, in order,
# after a CREATE TABLE failed because the table is already there but the
# original DROP could not find it. Oracle folds unquoted identifiers to
# upper case in the data dictionary, so the name the caller holds and the
# name ALL_TABLES stores can differ.


def _lookup_executor(rows=None, error=None):
    """Query executor stub, shaped like the call the lookup actually makes.

    ``execute_query(connection, sql, params)`` — three positional arguments,
    returning a list of row mappings.
    """
    query_executor = MagicMock()
    if error is not None:
        query_executor.execute_query.side_effect = error
    else:
        query_executor.execute_query.return_value = rows
    return query_executor


@pytest.mark.parametrize("rows", [[], None], ids=["no_rows", "no_result"])
def test_oracle_retry_drop_strategies_stand_on_the_names_passed_in(rows):
    """No dictionary match: the quoted then unquoted forms of the caller's names."""
    connection = object()
    query_executor = _lookup_executor(rows=rows)

    strategies = OracleQuirks().build_retry_drop_strategies(
        query_executor, connection, "HR", "EMPLOYEES"
    )

    assert strategies == ['"HR"."EMPLOYEES"', "HR.EMPLOYEES"]
    # The lookup runs on the connection it was handed, not one of its own.
    assert query_executor.execute_query.call_args.args[0] is connection


@pytest.mark.parametrize(
    "row",
    [
        {"OWNER": "HR", "TABLE_NAME": "EMPLOYEES"},
        {"owner": "HR", "table_name": "EMPLOYEES"},
    ],
    ids=["upper_case_keys", "lower_case_keys"],
)
def test_oracle_retry_drop_tries_the_dictionary_name_first(row):
    """The upper-cased name ALL_TABLES stores is the one a DROP has to target.

    It is prepended, not appended: trying the caller's lower-case form first
    would fail again for the same reason the first DROP did.
    """
    strategies = OracleQuirks().build_retry_drop_strategies(
        _lookup_executor(rows=[row]), object(), "hr", "employees"
    )

    assert strategies == ['"HR"."EMPLOYEES"', '"hr"."employees"', "hr.employees"]


def test_oracle_retry_drop_tries_a_different_owner_first():
    """The owner ALL_TABLES reports wins over the schema the caller assumed."""
    strategies = OracleQuirks().build_retry_drop_strategies(
        _lookup_executor(rows=[{"OWNER": "APP_OWNER", "TABLE_NAME": "ORDERS"}]),
        object(),
        "APP",
        "ORDERS",
    )

    assert strategies == ['"APP_OWNER"."ORDERS"', '"APP"."ORDERS"', "APP.ORDERS"]


def test_oracle_retry_drop_lookup_skips_recycle_bin_entries():
    """A dropped table lingers in ALL_TABLES as ``BIN$…``; dropping it again
    would target the wrong object, so those rows are excluded."""
    query_executor = _lookup_executor(rows=[])

    OracleQuirks().build_retry_drop_strategies(query_executor, object(), "HR", "EMPLOYEES")

    assert "BIN$" in query_executor.execute_query.call_args.args[1]


def test_oracle_retry_drop_strategies_survive_a_failing_lookup():
    """The dictionary query is best-effort — the caller still gets its list.

    Letting the failure out would turn a retry that might have worked into a
    hard error, on a path only reached because something already went wrong.
    """
    query_executor = _lookup_executor(error=RuntimeError("ORA-00942: table or view"))

    strategies = OracleQuirks().build_retry_drop_strategies(
        query_executor, object(), "HR", "EMPLOYEES"
    )

    assert strategies == ['"HR"."EMPLOYEES"', "HR.EMPLOYEES"]


def test_oracle_retry_drop_lookup_failure_logs_under_this_modules_own_logger(caplog):
    """The swallowed failure is attributed to the module that emits it.

    A logger named for some other namespace sends the only trace of this
    failure somewhere the reader of this file has no reason to look.
    """
    query_executor = _lookup_executor(error=RuntimeError("dictionary unavailable"))

    with caplog.at_level(logging.DEBUG):
        OracleQuirks().build_retry_drop_strategies(query_executor, object(), "HR", "EMPLOYEES")

    emitters = {
        record.name for record in caplog.records if "dictionary unavailable" in record.getMessage()
    }
    assert emitters == {"dblift.db.plugins.oracle.quirks"}
