"""Public consumers must describe statements that execution actually sends."""

import pytest

from dblift.core.exceptions import (
    TransactionStatementError,
    UnsafeStatementSplitError,
    UnsupportedMetaCommandError,
)
from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.execution_statement import (
    execution_units,
    neutralise_transaction_statements,
)
from dblift.core.migration.sql.lint_rules import find_issues
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_model.base import ParseResult
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.db.plugins.snowflake.statement_parser import SnowflakeStatementParser


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


def test_hybrid_does_not_extract_from_a_script_with_no_executed_statements(monkeypatch) -> None:
    parser = SqlParserFactory("sqlserver").get_parser()
    monkeypatch.setattr(
        parser.regex_parser,
        "parse_sql",
        lambda *_args, **_kwargs: ParseResult(success=True, statements=[], errors=[]),
    )

    def forbidden_extraction(*_args, **_kwargs):
        raise AssertionError("whole-script extraction was used")

    monkeypatch.setattr(parser, "extract_objects", forbidden_extraction)
    result = parser.parse_sql("CREATE TABLE ghost(id INT);\nGO 0")
    assert result.success
    assert result.statements == []
    assert result.tables == []


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

    assert [statement.operation for statement in analysis.statements] == [
        "SELECT",
        "DROP",
        "SELECT",
    ]
    assert "drop-table" in {finding.code for finding in find_issues(analysis, "postgresql")}


def test_mysql_custom_delimiter_cannot_hide_drop_from_lint() -> None:
    sql = "DELIMITER //\nSELECT 1; DROP TABLE users; SELECT 2//\nDELIMITER ;"

    analysis = analyse_script(sql, "mysql")

    assert [statement.operation for statement in analysis.statements] == [
        "SELECT",
        "DROP",
        "SELECT",
    ]
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


def test_sqlglot_parser_never_resplits_a_scanner_refusal(monkeypatch) -> None:
    from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser

    def refuse(self, sql_content: str, strict_tokenizer: bool = False) -> list[str]:
        raise UnsafeStatementSplitError("scanner refused")

    monkeypatch.setattr(PostgreSqlRegexParser, "split_statements", refuse)
    with pytest.raises(UnsafeStatementSplitError, match="scanner refused"):
        SqlGlotParser("postgresql").split_statements("SELECT 1; SELECT 2;")


def test_snowflake_records_cover_original_statement_spans() -> None:
    sql = "\nSELECT 'a;b';\nSELECT 2;"
    records = SnowflakeStatementParser().split(sql)
    assert [sql[record.source_start : record.source_end] for record in records] == [
        "\nSELECT 'a;b';",
        "\nSELECT 2;",
    ]
    assert [record.text for record in records] == ["SELECT 'a;b'", "SELECT 2"]


def test_transaction_policy_sees_inner_commit_in_atomic_pg_unit() -> None:
    sql = r"SELECT 1 \; COMMIT;"
    statements = SqlAnalyzer("postgresql").split_statements(sql)
    assert len(statements) == 1
    with pytest.raises(TransactionStatementError, match="COMMIT manages the transaction"):
        neutralise_transaction_statements(
            statements,
            dialect="postgresql",
            log=NullLog(),
            content=sql,
        )


def test_transaction_policy_preserves_sqlserver_procedural_begin_batch() -> None:
    sql = "BEGIN SELECT 1; END; SELECT 2;"
    statements = SqlAnalyzer("sqlserver").split_statements(sql)
    assert (
        neutralise_transaction_statements(
            statements,
            dialect="sqlserver",
            log=NullLog(),
            content=sql,
        )
        == statements
    )


def test_execution_units_filter_go_zero_and_keep_psql_combination_atomic() -> None:
    assert execution_units("SELECT 1;\nGO 0\nSELECT 2;", "sqlserver") == ["SELECT 2;"]
    sql = r"SELECT 1 \; CREATE INDEX CONCURRENTLY ix ON users(id);"
    assert len(execution_units(sql, "postgresql")) == 1


def test_sqlglot_public_object_extraction_omits_skipped_batch() -> None:
    parser = SqlGlotParser("sqlserver")
    assert parser.extract_objects("CREATE TABLE ghost(id INT);\nGO 0") == []


def test_sqlglot_public_validation_reports_scanner_refusal() -> None:
    result = SqlGlotParser("sqlserver").validate_sql(":setvar schema dbo\nSELECT 1;\n")
    assert result["valid"] is False
    assert any(":setvar" in error for error in result["errors"])


def test_hybrid_public_object_extraction_does_not_rescan_refused_script() -> None:
    parser = SqlParserFactory("sqlserver").get_parser()
    with pytest.raises(UnsupportedMetaCommandError, match=":setvar"):
        parser.extract_objects(":setvar schema dbo\nCREATE TABLE ghost(id INT);")


def test_sqlglot_fragment_analysis_has_explicit_semantic_entry_point() -> None:
    result = SqlGlotParser("postgresql").parse_fragment("SELECT 1")
    assert result.success
    assert len(result.statements) == 1
