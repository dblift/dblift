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

# Dialects whose parser rejects the script although the splitter accepts it.
PARSER_REJECTS = {
    **dict.fromkeys(
        [
            "postgresql",
            "alloydb",
            "aurora-postgresql",
            "citus",
            "cockroachdb",
            "neon",
            "redshift",
            "supabase",
            "timescaledb",
            "yugabytedb",
            "snowflake",
        ],
        UNBALANCED_PAREN,
    ),
    "mysql": UNBALANCED_BACKTICK,
    "mariadb": UNBALANCED_BACKTICK,
}


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


@pytest.mark.parametrize("dialect", sorted(PARSER_REJECTS))
def test_script_the_parser_rejects_is_invalid_with_its_message(dialect):
    analyzer = _analyzer(dialect)
    sql = PARSER_REJECTS[dialect]
    expected_valid, expected_message = _parser_verdict(analyzer, sql)
    assert expected_valid is False and expected_message

    assert analyzer.validate_sql(sql) == (False, expected_message)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql", [VALID, UNCLOSED_COMMENT, UNCLOSED_QUOTE, UNBALANCED_PAREN, UNBALANCED_BACKTICK]
)
def test_every_parser_reports_valid_and_errors(dialect, sql):
    raw = _analyzer(dialect)._db_specific_parser.validate_sql(sql)
    assert isinstance(raw["valid"], bool)
    assert isinstance(raw["errors"], list)
