"""Shared lexical policies and migrated execution entry points."""

import importlib.util
from dataclasses import replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC
from dblift.db.provider_registry import ProviderRegistry


@pytest.mark.parametrize(
    "dialect",
    [
        "postgresql",
        "alloydb",
        "aurora-postgresql",
        "citus",
        "cockroachdb",
        "neon",
        "supabase",
        "timescaledb",
        "yugabytedb",
    ],
)
def test_execution_uses_plugin_rules_without_constructing_a_regex_parser(monkeypatch, dialect):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy parser construction reached")

    monkeypatch.setattr(SqlParserFactory, "__init__", forbidden)
    monkeypatch.setattr(SqlParserFactory, "get_parser", forbidden)
    assert StatementSplitter(dialect).split_statements(
        "CREATE TABLE t(begin int); SELECT begin atomic FROM t; SELECT 2;"
    ) == ["CREATE TABLE t(begin int);", "SELECT begin atomic FROM t;", "SELECT 2;"]


def test_replaced_scanner_modules_are_absent():
    for name in ("postgresql_tokenizer", "postgresql_statement_parser"):
        assert importlib.util.find_spec(f"dblift.db.plugins.postgresql.parser.{name}") is None


def test_rules_change_boundaries_without_a_dialect_scanner():
    script = "SELECT (1; SELECT 2); SELECT 3;"
    assert len(LexicalEngine(POSTGRESQL_SPEC).split(script)) == 2
    assert len(LexicalEngine(LexicalSpec(name="plain")).split(script)) == 3
    comment_script = "/* outer /* inner */ SELECT 1; */ SELECT 2;"
    assert len(LexicalEngine(POSTGRESQL_SPEC).split(comment_script)) == 1
    assert len(LexicalEngine(LexicalSpec(name="plain")).split(comment_script)) == 2
    routine = "CREATE FUNCTION f() RETURNS int BEGIN ATOMIC SELECT 1; SELECT 2; END;"
    assert len(LexicalEngine(POSTGRESQL_SPEC).split(routine)) == 1
    assert len(LexicalEngine(replace(POSTGRESQL_SPEC, routine_heads=())).split(routine)) == 3


def test_redshift_preserves_backslash_strings_and_non_nested_comments():
    script = "SELECT 'a\\'b;c'; SELECT 2;"
    expected = ["SELECT 'a\\'b;c';", "SELECT 2;"]
    assert StatementSplitter("redshift").split_statements(script) == expected
    assert (
        SqlParserFactory("redshift", parser_type="regex").get_parser().split_statements(script)
        == expected
    )
    script = "/* outer /* inner */ SELECT 1; */ SELECT 2;"
    assert StatementSplitter("redshift").split_statements(script) == ["SELECT 1;", "*/ SELECT 2;"]
    assert len(StatementSplitter("postgresql").split_statements(script)) == 1
    assert ProviderRegistry.get_quirks("redshift").lexical_spec() == REDSHIFT_SPEC


@pytest.mark.parametrize(
    "head",
    [
        "CREATE FUNCTION",
        "CREATE PROCEDURE",
        "CREATE OR REPLACE FUNCTION",
        "CREATE OR REPLACE PROCEDURE",
    ],
)
def test_only_declared_routine_heads_activate_atomic_body(head):
    script = f"{head} f() RETURNS int BEGIN /* c */ ATOMIC SELECT CASE WHEN true THEN 1 END; SELECT 2; END; SELECT 3;"
    assert len(LexicalEngine(POSTGRESQL_SPEC).split(script)) == 2
    assert len(LexicalEngine(POSTGRESQL_SPEC).split("SELECT (begin atomic); SELECT 2;")) == 2


def test_comment_masking_keeps_quoted_comment_markers():
    script = "SELECT E'a\\'--b', $$/* literal */$$ /* outer /* inner */ end */;"
    expected = "SELECT E'a\\'--b', $$/* literal */$$  ;"
    assert LexicalEngine(POSTGRESQL_SPEC).blank_comments(script) == expected
    assert ProviderRegistry.get_quirks("postgresql").blank_comments(script) == expected


@pytest.mark.parametrize("strict", [False, True])
def test_refusal_cannot_be_softened_at_legacy_entry_point(strict):
    with pytest.raises(UnsafeStatementSplitError, match="line 1, column 8"):
        PostgreSqlRegexParser().split("SELECT $$open", strict_tokenizer=strict)


@pytest.mark.parametrize(
    "unit",
    [
        "SELECT E'a\\'b;c', $tag$x;y$tag$; /* outer /* inner */ */\n",
        "CREATE FUNCTION f() RETURNS int BEGIN ATOMIC SELECT CASE WHEN true THEN 1 END; SELECT 2; END;\n",
        "COPY t FROM STDIN; -- header\nrow\n\\.\n",
    ],
)
def test_source_slicing_cost_is_bounded_for_repeated_units(unit):
    class CountingText(str):
        sliced = 0

        def __getitem__(self, key):
            if isinstance(key, slice):
                self.sliced += len(range(*key.indices(len(self))))
            return super().__getitem__(key)

    for repetitions in (100, 400):
        script = CountingText(unit * repetitions)
        assert len(LexicalEngine(POSTGRESQL_SPEC).split(script)) == repetitions
        assert script.sliced <= 12 * len(script)


def test_extraction_does_not_lose_sql_after_a_comment_marker_in_an_escape_string():
    script = "SELECT E'a\\'--b'; DROP TABLE visible;"
    objects = PostgreSqlRegexParser().extract_objects(script)
    assert [obj.name for obj in objects] == ["visible"]


def test_combined_statement_starts_a_fresh_routine_head():
    script = (
        "SELECT 0 \\; CREATE FUNCTION f() RETURNS int LANGUAGE SQL "
        "BEGIN ATOMIC SELECT 1; END; SELECT 2;"
    )
    records = LexicalEngine(POSTGRESQL_SPEC).split(script)
    assert [record.text for record in records] == [
        "SELECT 0 ; CREATE FUNCTION f() RETURNS int LANGUAGE SQL BEGIN ATOMIC SELECT 1; END",
        "SELECT 2",
    ]
    assert records[0].multi
    assert records[0].analysis_statements == (
        "SELECT 0",
        "CREATE FUNCTION f() RETURNS int LANGUAGE SQL BEGIN ATOMIC SELECT 1; END",
    )


def test_copy_column_does_not_start_a_data_header():
    script = "CREATE TABLE stdin(copy int); SELECT copy FROM stdin; SELECT 2;"
    assert StatementSplitter("postgresql").split_statements(script) == [
        "CREATE TABLE stdin(copy int);",
        "SELECT copy FROM stdin;",
        "SELECT 2;",
    ]
    assert all(record.kind == "sql" for record in LexicalEngine(POSTGRESQL_SPEC).split(script))
