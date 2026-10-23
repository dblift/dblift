"""Shared lexical policies and migrated execution entry points."""

import importlib.util
from dataclasses import replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser


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
    assert len(LexicalEngine(LexicalSpec(name="plain", text_blanks=" \t\n\r")).split(script)) == 3
    comment_script = "/* outer /* inner */ SELECT 1; */ SELECT 2;"
    assert len(LexicalEngine(POSTGRESQL_SPEC).split(comment_script)) == 1
    assert (
        len(LexicalEngine(LexicalSpec(name="plain", text_blanks=" \t\n\r")).split(comment_script))
        == 2
    )
    routine = "CREATE FUNCTION f() RETURNS int BEGIN ATOMIC SELECT 1; SELECT 2; END;"
    assert len(LexicalEngine(POSTGRESQL_SPEC).split(routine)) == 1
    assert len(LexicalEngine(replace(POSTGRESQL_SPEC, routine_heads=())).split(routine)) == 3


def test_redshift_preserves_backslash_strings_and_nested_comments():
    script = "SELECT 'a\\'b;c'; SELECT 2;"
    expected = ["SELECT 'a\\'b;c';", "SELECT 2;"]
    assert StatementSplitter("redshift").split_statements(script) == expected
    assert (
        SqlParserFactory("redshift", parser_type="regex").get_parser().split_statements(script)
        == expected
    )
    script = "/* outer /* inner */ SELECT 1; */ SELECT 2;"
    assert StatementSplitter("redshift").split_statements(script) == ["SELECT 2;"]
    assert StatementSplitter("postgresql").split_statements(script) == ["SELECT 2;"]
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
        facts_parser("postgresql").split("SELECT $$open")


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
    objects = facts_parser("postgresql").extract_objects(script)
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


def test_postgresql_keeps_parameter_tokens_and_the_quoted_identifier_escape():
    tokens = LexicalTokenizer('SELECT $1, "a""b"', spec=POSTGRESQL_SPEC).tokenize()
    assert [(t.type, t.text) for t in tokens] == [
        (TokenType.KEYWORD, "SELECT"),
        (TokenType.SYMBOL, "$1"),
        (TokenType.SYMBOL, ","),
        (TokenType.IDENTIFIER, '"a""b"'),
    ]


def test_other_specs_keep_the_new_defaults():
    from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
    from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
    from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
    from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

    for spec in (POSTGRESQL_SPEC, REDSHIFT_SPEC, SQLITE_SPEC, ORACLE_SPEC, SQLSERVER_SPEC):
        assert spec.delimiter_script is None
        assert spec.string_quote_doubling is True
    for spec in (POSTGRESQL_SPEC, SQLITE_SPEC, ORACLE_SPEC):
        assert spec.bracket_identifier == ()
        assert spec.leading_bom_is_blank is False
        assert spec.silent_unclaimed is False
        assert spec.batch_script is None
    assert POSTGRESQL_SPEC.placeholder_open == "${"
    assert SQLITE_SPEC.placeholder_open == "${"
    placeholder = LexicalTokenizer("SELECT ${x;", spec=POSTGRESQL_SPEC).tokenize()
    assert [x.text for x in placeholder if "${" in x.text] == ["${x;"]
    brackets = LexicalTokenizer("SELECT [a]", spec=POSTGRESQL_SPEC).tokenize()
    assert [x.text for x in brackets if x.type == TokenType.SYMBOL] == ["[", "]"]


def test_five_client_rules_are_exclusive():
    from itertools import combinations

    from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES
    from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_RULES
    from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_RULES
    from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
    from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

    rules = {
        "client_script": ORACLE_SPEC.client_script,
        "batch_script": SQLSERVER_SPEC.batch_script,
        "delimiter_script": MYSQL_RULES,
        "terminator_script": DB2_RULES,
        "segment_script": DUCKDB_RULES,
    }
    for first, second in combinations(rules, 2):
        with pytest.raises(
            ValueError, match="terminator_script and segment_script are mutually exclusive"
        ):
            LexicalSpec(name="x", text_blanks=" ", **{first: rules[first], second: rules[second]})
    for single in rules:
        LexicalSpec(name="x", text_blanks=" ", **{single: rules[single]})
    with pytest.raises(ValueError, match="segment_script and sqlite_shell are mutually exclusive"):
        LexicalSpec(name="x", text_blanks=" ", segment_script=DUCKDB_RULES, sqlite_shell=True)
    LexicalSpec(name="x", text_blanks=" ", sqlite_shell=True)


def test_other_specs_keep_segment_script_none():
    from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
    from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
    from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
    from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
    from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
    from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC
    from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
    from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

    for spec in (
        POSTGRESQL_SPEC,
        REDSHIFT_SPEC,
        SQLITE_SPEC,
        ORACLE_SPEC,
        SQLSERVER_SPEC,
        MYSQL_SPEC,
        MARIADB_SPEC,
        DB2_SPEC,
    ):
        assert spec.segment_script is None


def test_other_specs_keep_terminator_script_none():
    from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
    from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
    from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
    from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
    from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

    for spec in (
        POSTGRESQL_SPEC,
        REDSHIFT_SPEC,
        SQLITE_SPEC,
        ORACLE_SPEC,
        SQLSERVER_SPEC,
        MYSQL_SPEC,
        MARIADB_SPEC,
    ):
        assert spec.terminator_script is None
