"""Oracle splitting, analysis and extraction run on the shared lexical engine."""

import importlib.util

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser
from dblift.db.plugins.oracle.quirks import OracleQuirks
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC

SCRIPT = "CREATE TABLE a (x NUMBER);\nBEGIN NULL; END;\n/\nSELECT 1 FROM dual;"


def test_the_quirks_hand_the_engine_its_spec():
    assert OracleQuirks().lexical_spec() is ORACLE_SPEC


def test_execution_uses_the_spec_without_constructing_a_regex_parser(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy parser construction reached")

    monkeypatch.setattr(SqlParserFactory, "__init__", forbidden)
    monkeypatch.setattr(SqlParserFactory, "get_parser", forbidden)
    assert StatementSplitter("oracle").split_statements(SCRIPT) == [
        "CREATE TABLE a (x NUMBER);",
        "BEGIN NULL; END;",
        "SELECT 1 FROM dual;",
    ]


def test_replaced_scanner_modules_are_absent():
    assert (
        importlib.util.find_spec("dblift.db.plugins.oracle.parser.oracle_statement_parser") is None
    )


@pytest.mark.parametrize(
    "entry",
    ["split", "split_statements", "split_for_analysis", "split_for_extraction", "validate_sql"],
)
def test_oracle_entry_points_reach_the_engine(monkeypatch, entry):
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
    getattr(OracleParser(), entry)(SCRIPT)
    assert seen


def test_analysis_and_extraction_project_the_execution_records():
    parser = OracleParser()
    expected = ["CREATE TABLE a (x NUMBER)", "BEGIN NULL; END;", "SELECT 1 FROM dual"]
    assert parser.split_for_analysis(SCRIPT) == expected
    assert parser.split_for_extraction(SCRIPT) == expected
    assert SqlAnalyzer("oracle").split_statements_for_analysis(SCRIPT) == expected


@pytest.mark.parametrize("strict", [False, True])
def test_refusal_cannot_be_softened_at_the_legacy_entry_point(strict):
    with pytest.raises(UnsafeStatementSplitError, match="line 1, column 8"):
        OracleParser().split("SELECT q'[open", strict_tokenizer=strict)


def test_blank_input_has_no_records():
    parser = OracleParser()
    assert parser.split("") == [] and parser.split("  \n") == []
    assert parser.split_statements(" ") == []


def test_other_dialect_specs_are_unchanged():
    for spec in (POSTGRESQL_SPEC, SQLITE_SPEC):
        assert spec.client_script is None
        assert spec.alternative_quotes == ()
        assert spec.quoted_identifier_escape is True
        assert spec.parameter_prefix == "$"
        assert spec.placeholder_open == "${"


def test_a_line_terminator_is_not_a_terminator_for_other_dialects():
    assert StatementSplitter("postgresql").split_statements("SELECT 1\n/\nSELECT 2;") == [
        "SELECT 1\n/\nSELECT 2;"
    ]


def test_row_37_the_public_route_names_the_line_of_the_reference():
    for route in (OracleParser().split, SqlAnalyzer("oracle").split_statements):
        with pytest.raises(UnsafeStatementSplitError, match=r"&v on line 2 is undefined"):
            route("/ -- c\nSELECT &v FROM dual;")


def test_redaction_reads_oracle_text_without_client_directives():
    assert mask_string_literals("DEFINE p = 'secret'", "oracle") == "DEFINE p = '?'"
    # a directive line that opens a quote falls back to the first word, as before
    assert mask_string_literals("PROMPT it's secret", "oracle") == "PROMPT"
    assert describe_statement("CONNECT scott/tiger@db", "oracle") == "CONNECT scott"
    # pre-existing: nothing in this text is a literal or an IDENTIFIED BY value, so it is not masked
    assert mask_string_literals("CONNECT scott/tiger@db", "oracle") == "CONNECT scott/tiger@db"


def test_redaction_reads_alternative_quotes_as_the_splitter_does():
    # a q-quote is one literal (before: a masked quote followed by a stray quote)
    assert (
        mask_string_literals("CREATE USER u IDENTIFIED BY q'[pw]'", "oracle")
        == "CREATE USER u IDENTIFIED BY '?'"
    )
    # before: the statement fell back to its first word
    assert (
        mask_string_literals("CREATE TABLE t (a VARCHAR2(5) DEFAULT q'[it's]')", "oracle")
        == "CREATE TABLE t (a VARCHAR2(5) DEFAULT '?')"
    )


def test_redaction_keeps_comment_markers_inside_quoted_identifiers_out_of_literals():
    # before: the quote inside the identifier opened a literal that swallowed the comment
    assert (
        mask_string_literals("CREATE TABLE \"nq'\" (id NUMBER)/* it's */", "oracle")
        == "CREATE TABLE \"nq'\" (id NUMBER)/* it's */"
    )


def test_redaction_falls_back_to_the_first_word_for_an_unterminated_alternative_quote():
    # before: the text was masked as if the unterminated q-quote were a literal
    assert mask_string_literals("INSERT INTO t VALUES (Q':a'b);", "oracle") == "INSERT"
