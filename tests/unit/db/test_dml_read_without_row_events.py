"""A statement read without row events is different from an unread statement."""

import pytest

from dblift.db.dml_analysis import analyze_dml, updates_restore_key
from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    "dialect",
    [
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
    ],
)
def test_read_select_has_no_row_events_and_does_not_update_a_restore_key(dialect):
    quirks = ProviderRegistry.get_quirks(dialect)
    statement = "SELECT 1"

    assert quirks.statement_facts(statement).events == frozenset()
    assert analyze_dml(statement, quirks=quirks).events == set()
    assert updates_restore_key(statement, ["id"], quirks=quirks) is False


@pytest.mark.parametrize(
    "dialect",
    [
        "duckdb",
        "mariadb",
        "mysql",
        "oracle",
        "postgresql",
        "redshift",
        "snowflake",
        "sqlite",
        "sqlserver",
    ],
)
def test_read_create_table_has_no_row_events_and_does_not_update_a_restore_key(dialect):
    quirks = ProviderRegistry.get_quirks(dialect)
    statement = "CREATE TABLE t (id INT)"
    facts = quirks.statement_facts(statement)

    assert not facts.opaque
    assert facts.events == frozenset()
    assert analyze_dml(statement, quirks=quirks).events == set()
    assert updates_restore_key(statement, ["id"], quirks=quirks) is False


def test_unread_db2_create_table_still_fails_closed():
    quirks = ProviderRegistry.get_quirks("db2")
    statement = "CREATE TABLE t (id INT)"

    assert quirks.statement_facts(statement).opaque
    assert analyze_dml(statement, quirks=quirks).events is None
    assert updates_restore_key(statement, ["id"], quirks=quirks) is True


@pytest.mark.parametrize(
    ("dialect", "statement"),
    (
        ("snowflake", "CREATE TABLE t AS SELECT id FROM src"),
        ("snowflake", "CREATE TABLE t CLONE src"),
        ("snowflake", "CREATE OR REPLACE TABLE t (id INT)"),
        ("snowflake", "CREATE OR REPLACE TABLE t AS SELECT id FROM src"),
        ("postgresql", "CREATE TABLE t AS SELECT id FROM src"),
        ("duckdb", "CREATE TABLE t AS SELECT id FROM src"),
    ),
)
def test_table_creation_with_unproved_row_effects_stays_unknown(dialect, statement):
    quirks = ProviderRegistry.get_quirks(dialect)

    assert quirks.statement_facts(statement).events is None
    assert analyze_dml(statement, quirks=quirks).events is None
    assert updates_restore_key(statement, ["id"], quirks=quirks) is True


@pytest.mark.parametrize(
    ("dialect", "statement"),
    [
        ("db2", "SET CURRENT SCHEMA = 'APP'"),
        ("mysql", "SET NAMES utf8mb4"),
        ("mariadb", "SET NAMES utf8mb4"),
        ("postgresql", "SET search_path TO public"),
    ],
)
def test_session_set_does_not_update_a_restore_key(dialect, statement):
    quirks = ProviderRegistry.get_quirks(dialect)

    assert quirks.statement_facts(statement).events == frozenset()
    assert analyze_dml(statement, quirks=quirks).events == set()
    assert updates_restore_key(statement, ["id"], quirks=quirks) is False


@pytest.mark.parametrize(
    ("dialect", "statement"),
    [
        ("db2", "SET INTEGRITY FOR t IMMEDIATE CHECKED"),
        ("db2", "SET CURRENT SCHEMA = 'APP"),
        ("db2", "SET CURRENT SCHEMA = UPDATE"),
        ("mysql", "SET @id = 1"),
        ("postgresql", "SET ROLE writer"),
    ],
)
def test_unread_set_still_fails_closed(dialect, statement):
    quirks = ProviderRegistry.get_quirks(dialect)

    assert quirks.statement_facts(statement).events is None
    assert analyze_dml(statement, quirks=quirks).events is None
    assert updates_restore_key(statement, ["id"], quirks=quirks) is True


def test_unread_procedural_update_still_fails_closed():
    quirks = ProviderRegistry.get_quirks("postgresql")
    statement = "DO $$ BEGIN UPDATE t SET id = 2; END $$"

    assert analyze_dml(statement, quirks=quirks).events is None
    assert updates_restore_key(statement, ["id"], quirks=quirks) is True


@pytest.mark.parametrize(
    "statement", ("SELECT * FROM", "VALUES (", "WITH c AS (SELECT 1) SELECT * FROM")
)
def test_unread_db2_query_still_fails_closed(statement):
    quirks = ProviderRegistry.get_quirks("db2")

    assert quirks.statement_facts(statement).events is None
    assert analyze_dml(statement, quirks=quirks).events is None
    assert updates_restore_key(statement, ["id"], quirks=quirks) is True


@pytest.mark.parametrize(
    "statement",
    (
        "SELECT 2",
        "SELECT id FROM t",
        "SELECT 1 FROM SYSIBM.SYSDUMMY1",
        "VALUES 2",
        "WITH c AS (SELECT id FROM t) SELECT id FROM c",
    ),
)
def test_valid_db2_query_has_no_row_events(statement):
    quirks = ProviderRegistry.get_quirks("db2")

    assert quirks.statement_facts(statement).events == frozenset()
    assert analyze_dml(statement, quirks=quirks).events == set()
    assert updates_restore_key(statement, ["id"], quirks=quirks) is False


@pytest.mark.parametrize(
    "statement",
    (
        "SELECT",
        "SELECT /*",
        "SELECT id FROM",
        "SELECT 1 FROM SYSIBM.",
        "WITH c AS (SELECT 1) SELECT * FROM",
        "WITH changed AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 2)) SELECT id FROM changed",
    ),
)
def test_unread_or_data_changing_db2_query_has_unknown_row_events(statement):
    quirks = ProviderRegistry.get_quirks("db2")

    assert quirks.statement_facts(statement).events is None
    assert analyze_dml(statement, quirks=quirks).events is None
    assert updates_restore_key(statement, ["id"], quirks=quirks) is True


@pytest.mark.parametrize(
    "statement",
    (
        "VALUES *",
        "VALUES (*)",
        "SELECT *",
        "SELECT id",
        "SELECT 1 2",
        "SELECT id FROM t extra",
        "SELECT id FROM t WHERE",
        "SELECT 1; UPDATE t SET id = 2",
        "WITH c AS (UPDATE t SET id = 2) SELECT id FROM c",
        "WITH c AS (SELECT id FROM t) SELECT id FROM FINAL /* x */ TABLE (UPDATE t SET id = 2)",
        "WITH c AS (SELECT id FROM t) SELECT id FROM c WHERE",
        "WITH c AS (SELECT id FROM t SELECT id FROM u) SELECT id FROM c",
    ),
)
def test_db2_query_requires_complete_read_only_grammar(statement):
    quirks = ProviderRegistry.get_quirks("db2")

    assert quirks.statement_facts(statement).events is None
    assert analyze_dml(statement, quirks=quirks).events is None
