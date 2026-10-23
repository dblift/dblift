"""Migrations and callbacks share placeholder and dialect script preparation."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.sql.statement_reader import StatementReader
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit


def _engine(dialect):
    provider = MagicMock()
    provider.execute_statement.return_value = 0
    log = MagicMock()
    return ExecutionEngine(
        provider,
        StatementReader(dialect=dialect, logger=log),
        log,
        placeholder_service=PlaceholderService({"owner": "APP", "env": "dev"}, log),
    )


@pytest.mark.parametrize("dialect", ["postgresql", "oracle", "sqlserver"])
def test_preparation_resolves_identifiers_without_changing_canonical_sql(dialect):
    engine = _engine(dialect)
    content = "CREATE TABLE ${owner}.log_${env} (id INT);"
    migration = make_migration(script_name="V1__log.sql", content=content, logger=engine.log)
    callback = make_migration(
        script_name="beforeMigrate__log.sql", content=content, logger=engine.log
    )
    for script in (migration, callback):
        script._sql_statements = [content]
    cached = [script._sql_statements for script in (migration, callback)]

    migration_statements = engine._prepare_sql_statements(
        migration, placeholder_service=engine.placeholder_service
    )
    callback_statements = engine._prepare_sql_statements(
        callback, placeholder_service=engine.placeholder_service
    )

    assert migration_statements == callback_statements
    assert len(callback_statements) == 1
    assert "APP.log_dev" in callback_statements[0]
    for script, original_cache in zip((migration, callback), cached):
        assert script.content == content
        assert script._sql_statements is original_cache


def test_callback_preprocesses_sqlplus_after_placeholders_and_discards_directives():
    engine = _engine("oracle")
    content = (
        "DEFINE owner = ${owner}\n"
        "PROMPT Creating log\n"
        "SET SERVEROUTPUT ON\n"
        "WHENEVER SQLERROR EXIT\n"
        "CREATE TABLE &owner..log_${env} (id INT);\n"
    )
    callback = make_migration(
        script_name="beforeMigrate__log.sql", content=content, logger=engine.log
    )
    migration = make_migration(script_name="V1__log.sql", content=content, logger=engine.log)
    callback._sql_statements = [content]
    cached = callback._sql_statements
    expected = engine.get_executable_sql_statements(migration, MigrateResult())
    assert len(expected) == 1
    assert "APP.log_dev" in expected[0]

    engine.execute_callback(callback)

    engine.provider.execute_statement.assert_called_once_with(expected[0])
    assert callback.content == content
    assert callback._sql_statements is cached
    engine.log.info.assert_any_call("[PROMPT] Creating log")


@pytest.mark.parametrize("dialect", ["postgresql", "oracle"])
def test_preparation_errors_keep_migration_result_and_callback_exception_contracts(dialect):
    engine = _engine(dialect)
    script = make_migration(
        script_name="beforeMigrate__log.sql", content="SELECT 1", logger=engine.log
    )
    failure = ValueError("invalid script")
    result = MigrateResult()

    with patch(
        "dblift.core.migration.executor.execution_engine.parse_migration_sql", side_effect=failure
    ):
        with pytest.raises(ValueError) as exc:
            engine._prepare_sql_statements(script)
        assert exc.value is failure
        assert engine._parse_sql_statements(script, result) is None
        assert "invalid script" in result.error
        with pytest.raises(ValueError) as exc:
            engine.execute_callback(script)
        assert exc.value is failure

    engine.provider.begin_transaction.assert_not_called()
    engine.provider.execute_statement.assert_not_called()


@pytest.mark.parametrize(
    "dialect, content",
    [
        ("sqlserver", "GO\nCREATE TABLE t (id INT)\nGO\n"),
        ("postgresql", "-- comment only\n;\nCREATE TABLE t (id INT);"),
        ("postgresql", "  ;\nCREATE TABLE t (id INT);"),
    ],
)
def test_callback_sends_only_the_statements_the_splitter_returns(dialect, content):
    engine = _engine(dialect)
    callback = make_migration(
        script_name="beforeMigrate__log.sql", content=content, logger=engine.log
    )

    engine.execute_callback(callback)

    engine.provider.execute_statement.assert_called_once()
    assert engine.provider.execute_statement.call_args.args[0].startswith("CREATE TABLE t (id INT)")
