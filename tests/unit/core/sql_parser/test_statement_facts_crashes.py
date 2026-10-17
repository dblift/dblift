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


BLANKS = [c for c in map(chr, range(0x80, 0x10000)) if c.isspace()]
BLANK_IDS = [f"U+{ord(c):04X}" for c in BLANKS]


@pytest.mark.parametrize("char", BLANKS, ids=BLANK_IDS)
@pytest.mark.parametrize("tail", ["", " /* note"], ids=["tokenizes", "token-error"])
@pytest.mark.parametrize("dialect", ("sqlite", "postgres", "mysql"))
def test_a_unicode_blank_inside_a_two_word_object_type_never_raises(dialect, tail, char):
    from dblift.core.migration.sql.script_analysis import analyse_script

    sql = f"CREATE VIRTUAL{char}TABLE t USING fts5(a){tail}"

    assert read_statement_facts(sql, dialect=dialect).operation == "CREATE"
    analysis = analyse_script(sql + ";", dialect)
    assert analysis.statements or analysis.errors
