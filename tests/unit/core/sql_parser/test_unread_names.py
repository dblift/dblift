"""The shared rule that withholds object names an engine may read differently, and its sites."""

from __future__ import annotations

import logging

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.unread_names import names_unreadable, statement_sources
from dblift.db.dml_analysis import analyze_dml, statement_dml_table
from dblift.db.provider_registry import ProviderRegistry

_quirks = ProviderRegistry.get_quirks

NBSP, ZWSP, ZWJ, ACCENT = " ", "​", "‍", "́"
LEGACY = (
    "mysql",
    "mariadb",
    "sqlserver",
    "snowflake",
    "redshift",
)


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.mark.parametrize("char", [NBSP, ZWSP, " ", "　", "﻿", "⁠", "\u0085"])
def test_one_of_the_22_characters_outside_quotes_makes_the_names_unreadable(char):
    assert names_unreadable(f"CREATE TABLE t{char}(id INT)", "postgres")


@pytest.mark.parametrize(
    "sql",
    [
        f"CREATE TABLE t (id INT) -- a{NBSP}b",
        f"CREATE TABLE t (id INT) /* a{NBSP}b */",
        f"INSERT INTO t VALUES ('a{NBSP}b')",
        f'CREATE TABLE "t{NBSP}" (id INT)',
        "CREATE TABLE t (id INT)",
    ],
)
def test_the_character_inside_a_string_quote_or_comment_is_not_in_a_name(sql):
    assert not names_unreadable(sql, "postgres")


def test_a_name_cut_short_by_a_non_ascii_character_is_unreadable():
    assert names_unreadable(f"CREATE TABLE t{ZWJ}(id INT)", "postgres", ["t"])
    assert names_unreadable(f"CREATE TABLE t{ACCENT} (id INT)", "postgres", ["t"])
    assert names_unreadable("CREATE TABLE té (id INT)", "postgres", ["t"])
    assert names_unreadable("CREATE TABLE ét (id INT)", "postgres", ["t"])


def test_a_name_read_whole_is_kept():
    sql = "CREATE TABLE tété (id INT)"
    assert not names_unreadable(sql, "postgres", ["tété"])
    assert not names_unreadable(sql, "oracle", ["TÉTÉ"])
    assert not names_unreadable("INSERT INTO t VALUES ('té')", "postgres", ["t"])


def test_an_unknown_dialect_name_is_tolerated():
    assert names_unreadable(f"CREATE TABLE t{NBSP}(id INT)", "no-such-dialect")
    assert names_unreadable(f"CREATE TABLE t{NBSP}(id INT)", None)


@pytest.mark.parametrize("dialect", LEGACY)
def test_parse_sql_names_nothing_and_says_so(dialect):
    result = SqlParserFactory(dialect).parse_sql(f"CREATE TABLE t{NBSP}(id INT);")
    (statement,) = result.statements
    assert statement.objects == [] and statement.affected_objects == []
    assert statement.names_unread


FACTS = ("postgresql", "cockroachdb", "oracle")


@pytest.mark.parametrize("dialect", FACTS)
@pytest.mark.parametrize("char", (NBSP, ZWSP))
def test_the_facts_reader_names_nothing_it_cannot_prove(dialect, char):
    sql = f"CREATE TABLE t{char}(id INT)"
    facts = _quirks(dialect).statement_facts(sql)
    assert facts.objects == () and facts.opaque
    (statement,) = SqlParserFactory(dialect).parse_sql(f"{sql};").statements
    assert statement.objects == [] and statement.affected_objects == []
    assert statement.names_unread
    assert SqlAnalyzer(dialect).extract_objects(sql) == []
    assert SqlAnalyzer(dialect).extract_objects("CREATE TABLE t (id INT)") != []


@pytest.mark.parametrize("dialect", LEGACY)
def test_parse_sql_keeps_naming_a_readable_statement(dialect):
    def read(sql):
        (statement,) = SqlParserFactory(dialect).parse_sql(sql).statements
        return [(o.name, o.schema) for o in statement.objects + statement.affected_objects]

    assert read(f"CREATE TABLE t (id INT);\n-- a{NBSP}b") == read("CREATE TABLE t (id INT);")
    assert read(f"INSERT INTO t VALUES ('a{NBSP}b');") == read("INSERT INTO t VALUES ('ab');")


@pytest.mark.parametrize("dialect", LEGACY)
def test_extract_objects_names_nothing_for_an_unreadable_statement(dialect):
    assert SqlParserFactory(dialect).extract_objects(f"CREATE TABLE t{NBSP}(id INT)") == []
    assert SqlParserFactory(dialect).extract_objects("CREATE TABLE t(id INT)") != []


@pytest.mark.parametrize("dialect", LEGACY)
def test_the_analyzer_names_nothing_for_an_unreadable_statement(dialect):
    analyzer = SqlAnalyzer(dialect)
    assert analyzer.extract_objects(f"CREATE TABLE t{NBSP}(id INT)") == []
    assert analyzer.extract_objects("CREATE TABLE t (id INT)") != []


@pytest.mark.parametrize("dialect", ("postgres", "mysql", "tsql", "oracle"))
def test_dml_analysis_names_no_table_for_an_unreadable_statement(dialect):
    statement = f"DELETE FROM t{NBSP}WHERE a = 1"
    assert statement_dml_table(statement, quirks=_quirks(dialect)) == ""
    mutation = analyze_dml(statement, quirks=_quirks(dialect))
    assert mutation.table == "" and mutation.events is None and mutation.updated_columns == []
    assert statement_dml_table("DELETE FROM t WHERE a = 1", quirks=_quirks(dialect)) == "t"


@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("mysql", "INSERT INTO t SELECT `té` FROM u"),
        ("tsql", "INSERT INTO t SELECT [té] FROM u"),
    ],
)
def test_a_quoted_identifier_is_not_a_name_cut_short(dialect, sql):
    assert not names_unreadable(sql, dialect, ["t"])


@pytest.mark.parametrize("dialect", LEGACY + ("oracle",))
@pytest.mark.parametrize(
    "sql", ["CREATE SEQUENCE q{c};", "CREATE SEQUENCE q{c}", "DROP TABLE t{c};"]
)
def test_a_name_that_ends_its_statement_is_read_with_the_blank_the_split_trimmed(dialect, sql):
    script = sql.format(c=NBSP)
    if dialect == "oracle":  # the driver would strip it and the engine rejects it: refused
        with pytest.raises(UnsafeStatementSplitError):
            SqlParserFactory(dialect).extract_objects(script)
        return
    if dialect == "sqlserver" and sql == "CREATE SEQUENCE q{c}":
        # Measured (test_statement_edge_blanks.py SQLSERVER_UNICODE): U+00A0 is a blank to SQL Server,
        # so the record text drops it and the name ends the script as it does when terminated.
        assert [o.name.lower() for o in SqlParserFactory(dialect).extract_objects(script)] == ["q"]
        assert not any(
            s.names_unread for s in SqlParserFactory(dialect).parse_sql(script).statements
        )
        return
    assert SqlParserFactory(dialect).extract_objects(script) == []
    assert all(s.names_unread for s in SqlParserFactory(dialect).parse_sql(script).statements)


# The scanner's raw span for a name that ends the script. Oracle refuses a no-break space there, so
# its case uses an ideographic space, which it reads as a blank.
SPAN_SCANNERS = (
    "postgresql",
    "redshift",
    "cockroachdb",
    "mysql",
    "mariadb",
    "oracle",
    "sqlserver",
)


def _ending_blank(dialect):
    """A trailing white space character the dialect keeps in the text (a no-break space is a blank
    to SQL Server and refused by Oracle)."""
    return {"oracle": chr(0x3000), "sqlserver": chr(0x2029)}.get(dialect, NBSP)


@pytest.mark.parametrize("dialect", SPAN_SCANNERS)
def test_the_scanner_span_of_a_name_that_ends_the_script_holds_the_blank_except_for_oracle(dialect):
    """Green pin: only Oracle's last record ends at its last token."""
    script = f"DROP TABLE t{_ending_blank(dialect)}"
    records = SqlParserFactory(dialect, "regex").get_parser().split(script)
    assert len(records) == 1
    span = script[records[0].source_start : records[0].source_end]
    assert span == ("DROP TABLE t" if dialect == "oracle" else script)


@pytest.mark.parametrize("dialect", SPAN_SCANNERS)
def test_statement_sources_returns_the_untrimmed_text_of_a_name_that_ends_the_script(dialect):
    """Green pin: the span is the whole script for every dialect that keeps the blank."""
    script = f"DROP TABLE t{_ending_blank(dialect)}"
    scanner = SqlParserFactory(dialect, "regex").get_parser()
    statements = SqlAnalyzer(dialect).split_statements_for_analysis(script)
    # Oracle reads the ideographic space as a blank: its record, and so its span, ends at the name.
    assert statement_sources(scanner, script, statements) == [
        "DROP TABLE t" if dialect == "oracle" else script
    ]


KEEPS_THE_BLANK = ("postgresql", "redshift", "cockroachdb", "mysql", "mariadb", "sqlserver")


@pytest.mark.parametrize(
    "dialect",
    [
        pytest.param(
            d,
            marks=(
                []
                if d in KEEPS_THE_BLANK
                else pytest.mark.xfail(
                    strict=True,
                    reason="the record trims the blank, so the analysed text is shorter than its span",
                )
            ),
        )
        for d in SPAN_SCANNERS
        if d != "oracle"
    ],
)
def test_the_analysed_text_equals_its_span_once_the_record_keeps_the_blank(dialect):
    script = f"DROP TABLE t{_ending_blank(dialect)}"
    scanner = SqlParserFactory(dialect, "regex").get_parser()
    statements = SqlAnalyzer(dialect).split_statements_for_analysis(script)
    assert statements == statement_sources(scanner, script, statements) == [script]


@pytest.mark.parametrize("blank", ("\x0b", "\x0c", "\x0b　", "　\x0c "))
def test_oracle_span_ends_at_the_name_before_blanks_and_a_terminator(blank):
    scanner = SqlParserFactory("oracle", "regex").get_parser()
    script = f"DROP TABLE t　{blank};"
    assert statement_sources(scanner, script, ["DROP TABLE t"]) == ["DROP TABLE t;"]
    names = {
        obj.name.lower()
        for stmt in analyse_script(script, "oracle").statements
        for obj in stmt.objects
    }
    assert "t" in names


def test_a_character_the_engine_keeps_stays_in_the_span_before_a_terminator():
    scanner = SqlParserFactory("postgresql", "regex").get_parser()
    script = "DROP TABLE t 　;"
    [text] = scanner.split_for_extraction(script)
    assert statement_sources(scanner, script, [text])[0].startswith("DROP TABLE t ")


@pytest.mark.parametrize(
    "sql",
    ["CREATE TABLE t{c}(id INT);", "CREATE SEQUENCE q{c};", "DROP TABLE t{c};", "DROP TABLE t{c}"],
)
def test_db2_facts_name_nothing_for_a_name_the_engine_may_read_whole(sql):
    """Db2 reads statement facts: the reader leaves the objects unnamed instead of flagging the parse."""
    script = sql.format(c=NBSP)
    assert SqlParserFactory("db2").extract_objects(script) == []
    (statement,) = SqlParserFactory("db2").parse_sql(script).statements
    assert statement.objects == [] and statement.affected_objects == []


def test_the_facts_parser_marks_a_statement_whose_names_it_could_not_read():
    parser = SqlParserFactory("sqlite")
    (unread,) = parser.parse_sql("PRAGMA foreign_keys = ON").statements
    assert unread.names_unread is True
    (read,) = parser.parse_sql("CREATE TABLE t (a int)").statements
    assert read.names_unread is False
