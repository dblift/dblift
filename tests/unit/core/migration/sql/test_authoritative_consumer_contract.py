"""Public consumers must describe statements that execution actually sends."""

from dblift.core.logger import NullLog
from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.lint_rules import find_issues
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.snowflake.statement_parser import SnowflakeStatementParser
import pytest


def test_go_zero_create_cannot_generate_a_drop_undo() -> None:
    sql = "CREATE TABLE users(id INT);\nGO 0\nSELECT 2;"
    migration = Migration(
        script_name="V1__skip.sql",
        content=sql,
        version="1",
        description="skip",
        dialect="sqlserver",
    )

    assert migration.parse_sql_statements("sqlserver") == ["SELECT 2;"]
    undo = UndoScriptGenerator("sqlserver", logger=NullLog())._generate_undo_statements(migration)
    assert all("DROP TABLE" not in statement.sql.upper() for statement in undo)


def test_go_zero_only_creates_no_analysis_or_schema_objects() -> None:
    sql = "CREATE TABLE ghost(id INT);\nGO 0"
    parser = SqlParserFactory("sqlserver").get_parser()

    parsed = parser.parse_sql(sql)

    assert parsed.statements == []
    assert parsed.tables == []
    assert parser.extract_objects(sql) == []


def test_migration_sql_statements_property_uses_dialect_scanner() -> None:
    migration = Migration(
        script_name="V1__quoted.sql",
        content="SELECT 'a;b';\nGO 0\nSELECT 2;",
        dialect="sqlserver",
    )
    assert migration.sql_statements == ["SELECT 2;"]


def test_go_zero_then_executed_drop_is_a_lint_finding() -> None:
    sql = "CREATE TABLE users(id INT);\nGO 0\nDROP TABLE users;\nGO\n"

    analysis = analyse_script(sql, "sqlserver")

    assert [statement.operation for statement in analysis.statements] == ["DROP"]
    assert "drop-table" in {finding.code for finding in find_issues(analysis, "sqlserver")}


def test_postgresql_escaped_semicolons_cannot_hide_drop_from_lint() -> None:
    sql = r"SELECT 1 \; DROP TABLE users \; SELECT 2;"

    analysis = analyse_script(sql, "postgresql")

    assert [statement.operation for statement in analysis.statements] == ["SELECT", "DROP", "SELECT"]
    assert "drop-table" in {finding.code for finding in find_issues(analysis, "postgresql")}


def test_mysql_custom_delimiter_cannot_hide_drop_from_lint() -> None:
    sql = "DELIMITER //\nSELECT 1; DROP TABLE users; SELECT 2//\nDELIMITER ;"

    analysis = analyse_script(sql, "mysql")

    assert [statement.operation for statement in analysis.statements] == ["SELECT", "DROP", "SELECT"]
    assert "drop-table" in {finding.code for finding in find_issues(analysis, "mysql")}


def test_sqlserver_carriage_return_go_inside_literal_is_sql() -> None:
    sql = "SELECT 'a\rGO';\nGO\nSELECT 2;"

    assert SqlParserFactory("sqlserver").split_statements(sql) == ["SELECT 'a\rGO';", "SELECT 2;"]


def test_snowflake_scanner_failure_cannot_become_guessed_executable_sql(monkeypatch) -> None:
    def fail(self, sql_content: str, strict_tokenizer: bool = False) -> list[str]:
        raise ValueError("scanner bug")

    monkeypatch.setattr(SnowflakeStatementParser, "split_statements", fail)
    with pytest.raises(UnsafeStatementSplitError, match="scanner bug"):
        SqlAnalyzer("snowflake").split_statements("SELECT 'a;b'; SELECT 2;")
