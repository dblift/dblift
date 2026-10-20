"""A NUL byte in a PostgreSQL-family script is refused up front (docs/sql-parsing/postgresql.md, rows 31 to 31e).

libpq hands the query to the server as a C string, so everything from the NUL on is dropped without an
error: ``CREATE TABLE a(i int);<NUL>DROP TABLE a;`` runs only the CREATE and reports success.
"""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC

FAMILY = (
    "postgresql",
    "cockroachdb",
    "yugabytedb",
    "redshift",
    "alloydb",
    "aurora-postgresql",
    "citus",
    "neon",
    "supabase",
    "timescaledb",
)

CASES = [
    ("CREATE TABLE a(i int);\x00DROP TABLE a;", 1, 23),
    ("SELECT 1;\x00SELECT 2;", 1, 10),
    ("SELECT 'a\x00b';", 1, 10),
    ("CREATE TABLE c\x00d (x int);", 1, 15),
    ("SELECT 1;\n-- a\x00b\nSELECT 2;", 2, 5),
    ("SELECT 1;\r\n\x00", 2, 1),
    ("/* a\n\x00 */ SELECT 1;", 2, 1),
    ('SELECT "a\x00b";', 1, 10),
    ("SELECT $$a\x00b$$;", 1, 11),
    ("\x00", 1, 1),
]


@pytest.mark.parametrize("dialect", FAMILY)
@pytest.mark.parametrize("script, line, column", CASES)
def test_split_refuses_a_nul_with_its_position(dialect: str, script: str, line: int, column: int):
    with pytest.raises(UnsafeStatementSplitError) as caught:
        SqlAnalyzer(dialect).split_statements(script)
    message = str(caught.value)
    assert "NUL" in message
    assert f"line {line}, column {column}" in message


@pytest.mark.parametrize("spec", [POSTGRESQL_SPEC, REDSHIFT_SPEC])
def test_the_refusal_is_spec_data_read_by_the_shared_tokenizer(spec):
    with pytest.raises(UnsafeStatementSplitError):
        LexicalTokenizer("SELECT 1;\x00SELECT 2;", spec=spec).tokenize()


def test_the_analysis_projection_refuses_too():
    with pytest.raises(UnsafeStatementSplitError):
        PostgreSqlRegexParser().split("CREATE TABLE a(i int);\x00DROP TABLE a;")


@pytest.mark.parametrize("dialect", FAMILY)
def test_a_script_without_a_nul_still_splits(dialect: str):
    statements = SqlAnalyzer(dialect).split_statements("CREATE TABLE a(i int);\nDROP TABLE a;")
    assert [text.rstrip(";") for text in statements] == ["CREATE TABLE a(i int)", "DROP TABLE a"]


def test_the_refusal_is_not_a_property_of_the_shared_tokenizer_alone():
    assert DUCKDB_SPEC.refused_character == ""
    assert POSTGRESQL_SPEC.refused_character == "\x00"
