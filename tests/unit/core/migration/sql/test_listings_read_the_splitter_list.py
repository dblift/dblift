"""Analysis, the parsers' listings and ``Migration.sql_statements`` list what ``migrate`` sends."""

from __future__ import annotations

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script
from tests.support.facts_parser import facts_parser
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit

TAIL = "CREATE TABLE t(a int); -- bye\n/* tail */"
FACT_DIALECTS = ["sqlite", "duckdb"]


@pytest.mark.parametrize("dialect", [*FACT_DIALECTS, "postgresql"])
def test_a_trailing_comment_is_not_an_analysed_statement(dialect):
    analysis = analyse_script(TAIL, dialect)
    assert [s.sql for s in analysis.statements] == ["CREATE TABLE t(a int)"]


@pytest.mark.parametrize("dialect", ["mysql", "snowflake", "sqlserver"])
def test_an_analysed_statement_is_the_text_that_is_sent(dialect):
    script = "SELECT 1;\n\x1c # c\n;\nSELECT 2;" if dialect != "sqlserver" else "\x1c # c"
    sent = [s.sql for s in analyse_script(script, dialect).statements]
    assert any("\x1c" in sql for sql in sent), sent  # not rewritten by a strip


@pytest.mark.parametrize("dialect", FACT_DIALECTS)
def test_validate_sql_counts_one_statement_for_a_trailing_comment(dialect):
    parser = facts_parser(dialect)
    assert parser.validate_sql(TAIL)["statements_found"] == 1
    assert [s.sql_text for s in parser.parse_sql(TAIL).statements] == ["CREATE TABLE t(a int)"]
    assert len(parser.extract_objects(TAIL)) == 1


@pytest.mark.parametrize("dialect, piece", [("sqlite", "\xa0"), ("duckdb", "\x1c")])
def test_the_migration_shim_returns_a_piece_of_kept_characters(dialect, piece):
    migration = make_migration(
        script_name="V1__x.sql", content=f"SELECT 1;\n{piece};\nSELECT 2;", dialect=dialect
    )
    assert migration.parse_sql_statements(dialect) == ["SELECT 1", piece, "SELECT 2"]
    assert migration.sql_statements == migration.parse_sql_statements()
