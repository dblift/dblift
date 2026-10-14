"""SQL Server splitting, analysis and extraction run on the shared lexical engine."""

import importlib.util
import logging

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser
from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks

SCRIPT = "CREATE TABLE a (x INT);\nSELECT 1;\nGO\nSELECT 2\nGO 2\n"


def test_the_quirks_hand_the_engine_its_spec():
    assert SqlserverQuirks().lexical_spec() is SQLSERVER_SPEC


def test_execution_uses_the_spec_without_constructing_a_regex_parser(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy parser construction reached")

    monkeypatch.setattr(SqlParserFactory, "__init__", forbidden)
    monkeypatch.setattr(SqlParserFactory, "get_parser", forbidden)
    assert StatementSplitter("sqlserver").split_statements(SCRIPT) == [
        "CREATE TABLE a (x INT);\nSELECT 1;",
        "SELECT 2",
        "SELECT 2",
    ]


def test_replaced_scanner_module_is_absent():
    assert importlib.util.find_spec("dblift.db.plugins.sqlserver.parser._batches") is None


@pytest.mark.parametrize(
    "entry",
    ["split", "split_statements", "split_for_analysis", "split_for_extraction", "validate_sql"],
)
def test_sqlserver_entry_points_reach_the_engine(monkeypatch, entry):
    seen = []
    split = LexicalEngine.split
    split_statements = LexicalEngine.split_statements

    def counting_split(self, script, **kwargs):
        seen.append("split")
        return split(self, script, **kwargs)

    def counting_split_statements(self, script):
        seen.append("split_statements")
        return split_statements(self, script)

    monkeypatch.setattr(LexicalEngine, "split", counting_split)
    monkeypatch.setattr(LexicalEngine, "split_statements", counting_split_statements)
    getattr(SqlServerRegexParser(), entry)(SCRIPT)
    assert seen


def test_analysis_and_extraction_project_the_execution_records():
    parser = SqlServerRegexParser()
    expected = ["CREATE TABLE a (x INT);", "SELECT 1;", "SELECT 2"]
    assert parser.split_for_analysis(SCRIPT) == expected
    assert parser.split_for_extraction(SCRIPT) == expected
    assert SqlAnalyzer("sqlserver").split_statements_for_analysis(SCRIPT) == expected


@pytest.mark.parametrize("strict", [False, True])
def test_refusal_cannot_be_softened_at_the_legacy_entry_point(strict):
    with pytest.raises(
        UnsafeStatementSplitError, match="unterminated string opened at line 1, column 8"
    ):
        SqlServerRegexParser().split_statements("SELECT 'open", strict_tokenizer=strict)


@pytest.mark.parametrize("script", ["\xa0", "\x0c"])
def test_blank_but_not_empty_input_keeps_its_record(script):
    parser = SqlServerRegexParser()
    assert [r.text for r in parser.split(script)] == [""]
    assert parser.split_statements(script) == [""]


def test_empty_input_has_no_records():
    parser = SqlServerRegexParser()
    assert parser.split("") == [] and parser.split("  \n") == []


def test_other_dialect_specs_are_unchanged():
    for spec in (POSTGRESQL_SPEC, SQLITE_SPEC, ORACLE_SPEC):
        assert spec.batch_script is None
        assert spec.bracket_identifier == ()
        assert spec.silent_unclaimed is False
        assert spec.leading_bom_is_blank is False
        assert spec.redaction_reads_engine is True


def test_go_zero_is_logged_at_info(caplog):
    with caplog.at_level(logging.INFO, logger="dblift.core.sql_parser.lexical_engine"):
        assert SqlAnalyzer("sqlserver").split_statements("SELECT 1\nGO 0\nSELECT 2") == ["SELECT 2"]
    assert [(r.name, r.levelname) for r in caplog.records if "GO 0 follows" in r.getMessage()] == [
        ("dblift.core.sql_parser.lexical_engine", "INFO")
    ]


def test_redaction_masks_a_go_batch_text():
    assert (
        mask_string_literals("SELECT 1\nGO\nSELECT 'a'", "sqlserver") == "SELECT 1\nGO\nSELECT '?'"
    )


def test_redaction_masks_a_literal_after_a_placeholder_opener():
    assert (
        mask_string_literals("INSERT INTO t VALUES (${x, 'secret')", "sqlserver")
        == "INSERT INTO t VALUES (${x, '?')"
    )


@pytest.mark.parametrize(
    "sql, masked, described",
    [
        ("INSERT INTO t VALUES (N'secret')", "INSERT INTO t VALUES (N'?')", "INSERT INTO t"),
        ("SELECT [it's], 'x' FROM t", "SELECT [it's], '?' FROM t", "SELECT [it's]"),
        (
            "CREATE LOGIN l WITH PASSWORD = 'pw'",
            "CREATE LOGIN l WITH PASSWORD = '?'",
            "CREATE LOGIN l",
        ),
        ("SELECT $action, 'x'", "SELECT $action, '?'", "SELECT"),
        ("SELECT 'abc", "SELECT", "SELECT"),
        ("SELECT \"it's\", 'y'", "SELECT \"it's\", '?'", 'SELECT "it\'s"'),
        ("SELECT a%b, 'z'", "SELECT a%b, '?'", "SELECT a"),
        ("SELECT 1 -- it's\n, 'q'", "SELECT 1 -- it's\n, '?'", "SELECT 1"),
        ("SELECT 'a''b'", "SELECT '?'", "SELECT"),
    ],
)
def test_redaction_classes_keep_the_previous_strings(sql, masked, described):
    assert mask_string_literals(sql, "sqlserver") == masked
    assert describe_statement(sql, "sqlserver") == described


def test_redaction_reads_comments_the_way_the_server_does():
    # nested comment, no literal inside it: unchanged (the splitter's client reading would mask it)
    assert mask_string_literals("SELECT 1 /* a /* b */ 'x' */", "sqlserver") == (
        "SELECT 1 /* a /* b */ 'x' */"
    )
    # after /* /* */ the server's comment runs to the next star-slash, which ends it inside the
    # line comment text: the literals that follow are real literals and stay masked
    text = "SELECT 1 /* /* */\n-- it's -- */ n'x' '$(x)'"
    assert mask_string_literals(text, "sqlserver") == "SELECT 1 /* /* */\n-- it's -- */ n'?' '?'"
    assert describe_statement(text, "sqlserver") == "SELECT 1"


def test_redaction_describes_parameters_and_keeps_go_out_of_names():
    assert mask_string_literals("DECLARE @x = 'secret'", "sqlserver") == "DECLARE @x = '?'"
    assert describe_statement("DECLARE @x = 'secret'", "sqlserver") == "DECLARE @x"
    assert describe_statement("SELECT @@ROWCOUNT, 'w'", "sqlserver") == "SELECT @@ROWCOUNT"
    assert describe_statement("SELECT go INT FROM t", "sqlserver") == "SELECT"


def _spy_dialect_tokenizer(monkeypatch):
    from dblift.core.sql_parser import redaction

    calls = []
    real = redaction._dialect_tokenizer

    def spy(dialect):
        calls.append(dialect)
        return real(dialect)

    monkeypatch.setattr(redaction, "_dialect_tokenizer", spy)
    return calls


def test_redaction_reading_is_a_spec_field_sqlserver_keeps_the_dialect_reader(monkeypatch):
    calls = _spy_dialect_tokenizer(monkeypatch)
    assert SQLSERVER_SPEC.redaction_reads_engine is False
    assert describe_statement("DECLARE @x = 'secret'", "sqlserver") == "DECLARE @x"
    assert calls == ["sqlserver"]


def test_flipping_the_redaction_field_on_sqlserver_reads_the_engine(monkeypatch):
    from dataclasses import replace

    from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks

    calls = _spy_dialect_tokenizer(monkeypatch)
    spec = replace(SQLSERVER_SPEC, redaction_reads_engine=True)
    monkeypatch.setattr(SqlserverQuirks, "lexical_spec", lambda self: spec)
    assert describe_statement("DECLARE @x = 'secret'", "sqlserver") == "DECLARE"
    assert calls == []


def test_flipping_the_redaction_field_on_postgresql_reads_the_dialect_tokenizer(monkeypatch):
    from dataclasses import replace

    from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks

    calls = _spy_dialect_tokenizer(monkeypatch)
    mask_string_literals("SELECT 'a'", "postgresql")
    assert calls == []
    spec = replace(POSTGRESQL_SPEC, redaction_reads_engine=False)
    monkeypatch.setattr(PostgresqlQuirks, "lexical_spec", lambda self: spec)
    mask_string_literals("SELECT 'a'", "postgresql")
    assert calls == ["postgresql"]


def test_a_spec_that_reads_the_engine_for_masking_reads_client_lines_as_text(monkeypatch):
    from dataclasses import replace

    from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks

    spec = replace(SQLSERVER_SPEC, redaction_reads_engine=True)
    monkeypatch.setattr(SqlserverQuirks, "lexical_spec", lambda self: spec)
    # a client command line is refused by the splitter, but masking must still read its literal
    assert mask_string_literals(":setvar x 'secret'", "sqlserver") == ":setvar x '?'"
    assert (
        mask_string_literals("SELECT 1\nGO\nSELECT 'a'", "sqlserver") == "SELECT 1\nGO\nSELECT '?'"
    )


def test_shared_comment_masking_has_the_batch_comment_extents():
    assert LexicalEngine(SQLSERVER_SPEC).blank_comments("SELECT 1 /* c */") == "SELECT 1  "


@pytest.mark.parametrize("count", [0, 2])
def test_shared_analysis_projects_executed_batch_constituents(count):
    script = f"SELECT 1; SELECT 2;\nGO {count}\nSELECT 3; SELECT 4;"
    expected = ["SELECT 3;", "SELECT 4;"]
    if count:
        expected = ["SELECT 1;", "SELECT 2;"] + expected
    assert SqlServerRegexParser().split_for_analysis(script) == expected
    assert LexicalEngine(SQLSERVER_SPEC).split_for_analysis(script) == expected


def test_shared_analysis_keeps_sqlite_comment_only_segments():
    assert LexicalEngine(SQLITE_SPEC).split_for_analysis("SELECT 1; -- only") == [
        "SELECT 1",
        "-- only",
    ]
