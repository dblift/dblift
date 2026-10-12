"""Oracle parsing uses its executable SQL*Plus selection consistently."""

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser
from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer


def test_exit_shields_ignored_malformed_tail_from_tokenizer() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\nSELECT 'unterminated"

    assert OracleParser().split_statements(script) == ["SELECT 1 FROM dual;"]


def test_exit_does_not_parse_later_exits_or_malformed_tail() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\n" + "EXIT\n" * 1000 + "SELECT 'unterminated"

    assert OracleParser().split_statements(script) == ["SELECT 1 FROM dual;"]


def test_parse_sql_selects_the_same_statements_as_execution() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\nDROP TABLE users;"
    parser = OracleParser()

    assert [stmt.sql_text for stmt in parser.parse_sql(script).statements] == ["SELECT 1 FROM dual"]


def test_public_analyzer_uses_oracle_execution_selection() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\nDROP TABLE users;"

    assert SqlAnalyzer(dialect="oracle").split_statements_for_analysis(script) == [
        "SELECT 1 FROM dual"
    ]


def test_validate_sql_warns_for_isolated_plsql_fragment() -> None:
    result = OracleParser().validate_sql("END;")

    assert result["valid"] is True
    assert result["warnings"] == ["Fragment detected: END..."]


def test_repeated_record_and_string_projections_preserve_define_state() -> None:
    script = "DEFINE x = ok\nSELECT '&x' FROM dual;\nSET DEFINE OFF\n"
    parser = OracleStatementParser(OracleTokenizer(script).tokenize(), source=script)

    first = parser.split()

    assert parser.split() == first
    assert parser.split_statements() == ["SELECT 'ok' FROM dual;"]


def test_large_script_does_not_copy_each_remaining_token_suffix() -> None:
    class CountedTokens(list):
        copied = 0

        def __getitem__(self, index):
            result = super().__getitem__(index)
            if isinstance(index, slice):
                self.copied += len(result)
            return result

    script = "SELECT 1 FROM dual;\n" * 100
    tokens = CountedTokens(OracleTokenizer(script).tokenize())

    assert len(OracleStatementParser(tokens, source=script).split()) == 100
    assert tokens.copied < 10 * len(tokens)
