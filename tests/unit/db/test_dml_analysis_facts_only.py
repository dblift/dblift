"""DML analysis reads facts, or the sqlglot AST where a plugin has no reader; it never scans text."""

import pytest

from dblift.db import dml_analysis
from dblift.db.base_quirks import BaseQuirks
from dblift.db.dml_analysis import (
    DmlMutation,
    analyze_dml,
    dml_where_predicate,
    statement_dml_table,
    updates_restore_key,
)
from dblift.db.provider_registry import ProviderRegistry

UNREAD = DmlMutation(table="", events=None, updated_columns=[])
TRUNCATED_UPDATE = "UPDATE child SET parent_id ="
SQL_DIALECTS = [
    "db2",
    "duckdb",
    "mariadb",
    "mysql",
    "oracle",
    "postgresql",
    "redshift",
    "snowflake",
    "sqlite",
    "sqlserver",
]


def _no_reader(sqlglot_dialect):
    quirks = BaseQuirks()
    quirks.sqlglot_dialect = sqlglot_dialect
    return quirks


@pytest.mark.parametrize("dialect", SQL_DIALECTS)
def test_a_plugin_with_a_reader_reports_a_statement_it_cannot_read_as_unread(dialect):
    quirks = ProviderRegistry.get_quirks(dialect)
    assert quirks.analyze_dml("DELETE") == UNREAD
    assert quirks.statement_dml_table("MERGE INTO t1") == ""
    assert quirks.dml_where_predicate("DELETE") is None


@pytest.mark.parametrize("sqlglot_dialect", [None, "postgres", "tsql"])
def test_without_a_reader_a_statement_sqlglot_cannot_parse_is_unread(sqlglot_dialect):
    quirks = _no_reader(sqlglot_dialect)
    assert analyze_dml(TRUNCATED_UPDATE, quirks=quirks) == UNREAD
    assert analyze_dml("DELETE", quirks=quirks) == UNREAD
    assert statement_dml_table("MERGE INTO t1", quirks=quirks) == ""
    assert dml_where_predicate(TRUNCATED_UPDATE, quirks=quirks) is None


@pytest.mark.parametrize("plugin", ["mongodb", "cosmosdb"])
def test_a_plugin_without_sql_reports_a_statement_as_unread(plugin):
    quirks = ProviderRegistry.get_quirks(plugin)
    assert quirks.analyze_dml(TRUNCATED_UPDATE) == UNREAD
    assert quirks.statement_dml_table("MERGE INTO t1") == ""


def test_the_sqlglot_ast_still_reads_what_it_can_parse_without_a_reader():
    mutation = analyze_dml("UPDATE s.t SET a = 1 WHERE id = 2", quirks=_no_reader("postgres"))
    assert mutation == DmlMutation(table="s.t", events={"UPDATE"}, updated_columns=["a"])


def test_the_text_scanner_is_gone():
    for name in (
        "extract_dml_table_name",
        "_statement_dml_events",
        "_updated_column_names",
        "_is_upsert_with_update",
    ):
        assert not hasattr(dml_analysis, name), name


UNREAD_KEY_UPDATE = "UPDATE [dbo].[t] SET [id] = 5 WHERE x = 1"


@pytest.mark.parametrize(
    "quirks",
    [
        pytest.param(None, id="no-quirks"),
        pytest.param(_no_reader("mystery"), id="unknown-dialect"),
        pytest.param(ProviderRegistry.get_quirks("mongodb"), id="mongodb"),
        pytest.param(ProviderRegistry.get_quirks("cosmosdb"), id="cosmosdb"),
    ],
)
def test_an_unread_statement_is_assumed_to_touch_the_restore_key(quirks):
    """ "Could not read it" must never become "the key is untouched"."""
    assert updates_restore_key(UNREAD_KEY_UPDATE, ["id"], quirks=quirks) is True
    assert updates_restore_key("UPDATE child SET parent_id =", ["id"], quirks=quirks) is True


def test_a_statement_the_reader_does_read_keeps_its_answer():
    sqlserver = ProviderRegistry.get_quirks("sqlserver")
    assert updates_restore_key(UNREAD_KEY_UPDATE, ["id"], quirks=sqlserver) is True
    assert (
        updates_restore_key("UPDATE t SET name = 'x' WHERE id = 1", ["id"], quirks=sqlserver)
        is False
    )
    assert updates_restore_key("UPDATE t SET name = 'x'", [], quirks=sqlserver) is False


@pytest.mark.parametrize("dialect", SQL_DIALECTS)
def test_a_table_named_only_is_unread_not_guessed(dialect):
    """A reader leaves ``DELETE FROM only`` unread (ONLY is a keyword there); only the AST seam names it."""
    quirks = ProviderRegistry.get_quirks(dialect)
    assert quirks.statement_dml_table("DELETE FROM only WHERE a = 1") == ""
    assert statement_dml_table("DELETE FROM only WHERE a = 1", quirks=_no_reader(None)) == "only"
