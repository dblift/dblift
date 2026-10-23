"""``SqlAnalyzer.validate_sql`` returns the dialect parser's verdict and its first error."""

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.provider_registry import ProviderRegistry

DIALECTS = sorted(p.name for p in ProviderRegistry.list_plugins())

VALID = "CREATE TABLE a (x INT);\nSELECT 1;\n"
UNCLOSED_COMMENT = "SELECT 1;\n/* open"  # refused by the statement splitter
UNCLOSED_QUOTE = "SELECT 'abc;\nSELECT 2;"
UNBALANCED_PAREN = "SELECT (1;\nSELECT 2;"  # refused by the parser, not the splitter
UNBALANCED_BACKTICK = "SELECT `a FROM t;"


def _analyzer(dialect):
    analyzer = SqlAnalyzer(dialect)
    if analyzer._db_specific_parser is None:
        pytest.skip(f"{dialect} has no dialect parser: the structural fallback answers")
    return analyzer


def _parser_verdict(analyzer, sql):
    raw = analyzer._db_specific_parser.validate_sql(sql)
    return bool(raw["valid"]), (raw["errors"][0] if raw["errors"] else None)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_valid_script_is_valid_without_message(dialect):
    assert _analyzer(dialect).validate_sql(VALID) == (True, None)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("sql", [UNCLOSED_COMMENT, UNCLOSED_QUOTE])
def test_script_the_splitter_refuses_is_invalid_with_its_message(dialect, sql):
    analyzer = _analyzer(dialect)
    expected_valid, expected_message = _parser_verdict(analyzer, sql)
    assert expected_valid is False and expected_message  # the parser does refuse it

    assert analyzer.validate_sql(sql) == (False, expected_message)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql", [VALID, UNCLOSED_COMMENT, UNCLOSED_QUOTE, UNBALANCED_PAREN, UNBALANCED_BACKTICK]
)
def test_every_parser_reports_valid_and_errors(dialect, sql):
    raw = _analyzer(dialect)._db_specific_parser.validate_sql(sql)
    assert isinstance(raw["valid"], bool)
    assert isinstance(raw["errors"], list)


class _StubParser:
    def __init__(self, answer):
        self._answer = answer

    def validate_sql(self, sql):
        return self._answer


def _with_answer(answer):
    analyzer = SqlAnalyzer("postgresql")
    analyzer._db_specific_parser = _StubParser(answer)
    return analyzer.validate_sql("SELECT 1;")


@pytest.mark.parametrize(
    "answer, expected",
    [
        ({"success": False, "errors": ["boom"]}, (False, "boom")),
        ({"success": True, "errors": []}, (True, None)),
        ({"is_valid": False, "error_message": "legacy"}, (False, "legacy")),
        ({"valid": False, "errors": [], "error_message": "x"}, (False, "x")),
        ({"valid": False, "errors": ["first"], "error_message": "x"}, (False, "first")),
        ({"valid": True, "is_valid": False, "errors": []}, (True, None)),
        ({"valid": False, "is_valid": True, "errors": ["e"]}, (False, "e")),
    ],
)
def test_verdict_keys_and_message_precedence(answer, expected):
    assert _with_answer(answer) == expected


@pytest.mark.parametrize("answer", [{}, {"errors": []}, {"statements_found": 3}])
def test_a_parser_answer_without_verdict_is_not_valid(answer):
    is_valid, message = _with_answer(answer)
    assert is_valid is False
    assert message and "verdict" in message
