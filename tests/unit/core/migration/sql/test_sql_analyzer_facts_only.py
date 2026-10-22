"""``SqlAnalyzer`` reads objects from statement facts or reports none: it never guesses from text."""

import pytest

from dblift.core.migration.sql import sql_analyzer as sql_analyzer_module
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.redshift.quirks import RedshiftQuirks

NESTED_COMMENT = "/* outer /* inner */ DROP TABLE victim; still outer */\nSELECT 1"
MULTI_DROP = "DROP TABLE IF EXISTS a, b"
FOLDED = {"oracle", "snowflake"}
SQL_DIALECTS = [
    "alloydb",
    "aurora-postgresql",
    "citus",
    "cockroachdb",
    "db2",
    "duckdb",
    "mariadb",
    "mysql",
    "neon",
    "oracle",
    "postgresql",
    "redshift",
    "snowflake",
    "sqlite",
    "sqlserver",
    "supabase",
    "timescaledb",
    "yugabytedb",
]


def _names(objects):
    return [obj["object_name"] for obj in objects]


@pytest.mark.parametrize("dialect", [d for d in SQL_DIALECTS if d not in ("db2", "duckdb")])
def test_a_statement_the_text_scan_misread_is_read_from_facts(dialect):
    """The text scan named only the first table of a multi-table drop."""
    fold = str.upper if dialect in FOLDED else str.lower
    assert _names(SqlAnalyzer(dialect).extract_objects(MULTI_DROP)) == [
        f"default_schema.{fold('a')}",
        f"default_schema.{fold('b')}",
    ]


@pytest.mark.parametrize("dialect", ["db2", "duckdb"])
def test_a_commented_out_statement_names_no_object(dialect):
    """The text scan read the DROP inside a nested comment and named a table that is not touched."""
    assert SqlAnalyzer(dialect).extract_objects(NESTED_COMMENT) == []


def test_execution_mode_disables_object_extraction():
    analyzer = SqlAnalyzer("duckdb", analysis_mode="execution")
    assert analyzer.extract_objects("CREATE TABLE t (id INT)") == []
    result = analyzer.analyze_statement("CREATE TABLE t (id INT)")
    assert result["type"] == "DDL"
    assert result["objects"] == []


@pytest.mark.parametrize("dialect", ["mongodb", "cosmosdb"])
def test_a_dialect_without_a_reader_reports_no_objects(dialect):
    analyzer = SqlAnalyzer(dialect)
    assert analyzer.extract_objects("CREATE TABLE t (id INT)") == []
    assert analyzer.analyze_statement("CREATE TABLE t (id INT)")["objects"] == []


def test_a_plugin_whose_reader_is_removed_reports_no_objects(monkeypatch):
    monkeypatch.setattr(RedshiftQuirks, "statement_facts_class", None)
    assert SqlAnalyzer("redshift").extract_objects("CREATE TABLE t (id INT)") == []


def test_analysis_errors_are_not_retried_through_a_second_path(monkeypatch):
    analyzer = SqlAnalyzer("mongodb")

    def refuse(sql):
        raise ValueError("cannot classify")

    monkeypatch.setattr(analyzer, "get_statement_type", refuse)
    with pytest.raises(ValueError, match="cannot classify"):
        analyzer.analyze_statement("CREATE TABLE t (id INT)")


def test_the_text_extraction_is_gone():
    assert not hasattr(SqlAnalyzer, "_extract_objects_regex")
    for name in (
        "_DDL_OBJECT_RE",
        "_CREATE_INDEX_RE",
        "_names_an_object",
        "_qualified_object_name",
    ):
        assert not hasattr(sql_analyzer_module, name), name
