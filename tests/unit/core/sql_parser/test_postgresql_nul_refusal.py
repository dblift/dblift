"""A NUL byte in a PostgreSQL-family script is refused up front (docs/sql-parsing/postgresql.md, rows 31 to 31e).

libpq hands the query to the server as a C string, so everything from the NUL on is dropped without an
error: ``CREATE TABLE a(i int);<NUL>DROP TABLE a;`` runs only the CREATE and reports success.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.lexical_spec import SegmentScriptRules
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC
from tests.support.facts_parser import facts_parser

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
        facts_parser("postgresql").split("CREATE TABLE a(i int);\x00DROP TABLE a;")


@pytest.mark.parametrize("dialect", FAMILY)
def test_a_script_without_a_nul_still_splits(dialect: str):
    statements = SqlAnalyzer(dialect).split_statements("CREATE TABLE a(i int);\nDROP TABLE a;")
    assert [text.rstrip(";") for text in statements] == ["CREATE TABLE a(i int)", "DROP TABLE a"]


def test_one_refusal_field_set_serves_every_specification():
    assert DUCKDB_SPEC.refused_character == "\x00"
    assert POSTGRESQL_SPEC.refused_character == "\x00"
    assert not any(field.startswith("refused") for field in SegmentScriptRules.__dataclass_fields__)


@pytest.mark.parametrize("fields", [{"refused_character_name": "NUL"}, {"refused_reason": "r"}, {}])
def test_a_refused_character_needs_its_name_and_reason(fields):
    with pytest.raises(ValueError, match="refused_character needs"):
        replace(POSTGRESQL_SPEC, **{"refused_character_name": "", "refused_reason": "", **fields})
