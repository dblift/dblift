"""SQL parsing stays in services; the Migration API remains a 4.x shim."""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import Migration
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

pytestmark = pytest.mark.unit


def test_helper_splits_with_dialect_and_filters_empty_statements():
    helper = importlib.import_module("dblift.core.migration.sql.migration_sql_parser")
    assert helper.parse_migration_sql(
        SqlAnalyzer("sqlite"), "SELECT 'a;b'; SELECT 2;", NullLog()
    ) == ["SELECT 'a;b';", "SELECT 2;"]
    analyzer = MagicMock()
    analyzer.split_statements.return_value = ["", "  ", "SELECT 3"]
    assert helper.parse_migration_sql(analyzer, "SELECT 3;", NullLog()) == ["SELECT 3"]


def test_helper_split_failure_logs_and_uses_semicolon_fallback():
    helper = importlib.import_module("dblift.core.migration.sql.migration_sql_parser")
    analyzer, log = MagicMock(), MagicMock()
    analyzer.split_statements.side_effect = ValueError("bad parser")
    assert helper.parse_migration_sql(analyzer, " SELECT 1; ; SELECT 2;", log) == [
        "SELECT 1",
        "SELECT 2",
    ]
    log.warning.assert_called_once_with(
        "Error using SqlAnalyzer: bad parser. Falling back to simple semicolon-based parser."
    )


@pytest.mark.parametrize("operation", ["migration", "callback", "preview"])
def test_execution_paths_do_not_call_model_sql_parser(operation, monkeypatch):
    provider = MagicMock()
    provider.execute_statement.return_value = 0
    engine = ExecutionEngine(provider, SqlAnalyzer("sqlite"), NullLog())
    migration = Migration(script_name="V1__example.sql", content="CREATE TABLE example (id INT);")
    migration._sql_statements = ["canonical cache"]
    monkeypatch.setattr(
        Migration, "parse_sql_statements", MagicMock(side_effect=AssertionError("model parser"))
    )
    result = MigrateResult()
    if operation == "migration":
        engine.execute_migration(migration, result)
    elif operation == "callback":
        engine.execute_callback(migration)
    else:
        assert engine.get_executable_sql_statements(migration, result) == [
            "CREATE TABLE example (id INT);"
        ]
    assert not result.error, result.error
    if operation != "preview":
        provider.execute_statement.assert_called_once_with("CREATE TABLE example (id INT);")
    else:
        provider.execute_statement.assert_not_called()
    assert migration._sql_statements == ["canonical cache"]


def test_resolved_config_dialect_replaces_mismatched_analyzer(monkeypatch):
    wrong = SqlAnalyzer("sqlite")
    monkeypatch.setattr(
        wrong, "split_statements", MagicMock(side_effect=AssertionError("wrong dialect"))
    )
    config = SimpleNamespace(database=SimpleNamespace(type="mssql"))
    engine = ExecutionEngine(MagicMock(), wrong, NullLog(), config=config)
    migration = Migration(script_name="V1__x.sql", content="SELECT 1\nGO\nSELECT 2\nGO")
    monkeypatch.setattr(
        Migration, "parse_sql_statements", MagicMock(side_effect=AssertionError("model parser"))
    )
    assert engine._prepare_sql_statements(migration) == ["SELECT 1", "SELECT 2"]


def test_sqlplus_order_and_context_reset_without_model_parsing(monkeypatch):
    engine = ExecutionEngine(MagicMock(), SqlAnalyzer("oracle"), MagicMock())
    placeholders = PlaceholderService({"owner": "APP"}, NullLog())
    migration = Migration(
        script_name="V1__x.sql",
        content="DEFINE owner = ${owner}\nPROMPT Ready\nCREATE TABLE &owner..example (id INT);",
    )
    monkeypatch.setattr(
        Migration, "parse_sql_statements", MagicMock(side_effect=AssertionError("model parser"))
    )
    statements = engine._prepare_sql_statements(migration, placeholders)
    assert any("APP.example" in statement for statement in statements)
    assert all(
        "&owner" not in statement and "${owner}" not in statement for statement in statements
    )
    assert engine._current_sqlplus_ctx is not None
    engine.log.info.assert_any_call("[PROMPT] Ready")
    engine.sql_analyzer = SqlAnalyzer("sqlite")
    assert engine._prepare_sql_statements(
        Migration(script_name="V2__x.sql", content="SELECT 2;")
    ) == ["SELECT 2;"]
    assert engine._current_sqlplus_ctx is None


@pytest.mark.parametrize("success", [False, True])
def test_undo_fallback_does_not_call_model_sql_parser(success, monkeypatch):
    generator = UndoScriptGenerator("sqlite", logger=NullLog())
    generator.parser = SimpleNamespace(
        parse_sql=lambda *args, **kwargs: SimpleNamespace(success=success, statements=[])
    )
    migration = Migration(
        script_name="V1__x.sql",
        content="CREATE TABLE first (id INT); CREATE TABLE second (id INT);",
    )
    monkeypatch.setattr(
        Migration, "parse_sql_statements", MagicMock(side_effect=AssertionError("model parser"))
    )
    statements = generator._generate_undo_statements(migration)
    assert len(statements) == 2
    assert "second" in statements[0].sql
    assert "first" in statements[1].sql


@pytest.mark.parametrize("dialect", [None, "sqlite"])
@pytest.mark.parametrize("failure", ["construction", "splitting"])
def test_shim_falls_back_safely_for_known_and_default_dialects(dialect, failure, monkeypatch):
    monkeypatch.delenv("DBLIFT_DATABASE_TYPE", raising=False)
    analyzer = MagicMock()
    if failure == "construction":
        analyzer.side_effect = ValueError("bad parser")
    else:
        analyzer.return_value.split_statements.side_effect = ValueError("bad parser")
    monkeypatch.setattr("dblift.core.migration.sql.sql_analyzer.SqlAnalyzer", analyzer)
    migration = Migration(script_name="V1__x.sql", content="SELECT 1; SELECT 2;", logger=NullLog())
    assert migration.parse_sql_statements(dialect) == ["SELECT 1", "SELECT 2"]
    assert migration._sql_statements == ["SELECT 1", "SELECT 2"]


def test_shim_recomputes_canonical_cache_and_leaves_overrides_uncached():
    migration = Migration(script_name="V1__x.sql", content="SELECT 1;", dialect="sqlite")
    migration._sql_statements = ["stale"]
    assert migration.parse_sql_statements() == ["SELECT 1;"]
    cache = migration._sql_statements
    assert migration.parse_sql_statements(content_override="") == []
    assert migration.parse_sql_statements(content_override="SELECT 2;") == ["SELECT 2;"]
    assert migration._sql_statements is cache
    migration.content = "SELECT 3;"
    assert migration.parse_sql_statements() == ["SELECT 3;"]
    assert migration._sql_statements == ["SELECT 3;"]
