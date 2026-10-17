"""The statement facts reader reports what it cannot read; it never raises."""

from __future__ import annotations

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts

DIALECTS = ("sqlite", "duckdb", "postgres", "mysql", "oracle", "tsql", "redshift", "snowflake")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_index_without_columns_is_read_as_opaque(dialect):
    facts = read_statement_facts("CREATE INDEX ix ON t USING", dialect=dialect)

    assert facts.operation == "CREATE"
    assert facts.indexed_columns is None


@pytest.mark.parametrize("dialect", DIALECTS)
def test_index_without_columns_does_not_stop_undo_generation(dialect):
    from types import SimpleNamespace

    from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator

    migration = SimpleNamespace(
        content="CREATE INDEX ix ON t USING;", version="1", description="x", script_name="V1__x.sql"
    )
    UndoScriptGenerator("sqlite")._generate_undo_statements(migration)


def test_alter_session_is_read_as_opaque_on_snowflake():
    facts = read_statement_facts("ALTER SESSION SET LOCK_TIMEOUT = 0", dialect="snowflake")

    assert facts.operation == "ALTER"
    assert facts.objects == ()


@pytest.mark.parametrize("dialect", DIALECTS)
def test_alter_session_does_not_raise_on_any_dialect(dialect):
    assert read_statement_facts("ALTER SESSION SET LOCK_TIMEOUT = 0", dialect=dialect).operation
