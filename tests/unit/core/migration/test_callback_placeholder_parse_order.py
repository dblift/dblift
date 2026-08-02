"""Callback SQL must be placeholder-substituted *before* it is tokenised.

``execute_callback`` used to hand the raw file content to
``Migration.parse_sql_statements``, so the tokeniser saw ``${...}`` fragments.
Several dialect tokenisers do not recognise ``$``: they drop it and insert
whitespace around the braces, so a callback containing

    CREATE TABLE ${callback_schema}.callback_log_${env} (...)

reached the database as ``CREATE TABLE {callback_schema }.callback_log_$ {env }``
— rejected by the server (ORA-00903 on Oracle), aborting the whole ``migrate``
run before any versioned migration executed.

The migration path already substitutes first and passes the result as
``content_override``.  These tests pin the callback path to the same order by
asserting on the SQL text that reaches the provider.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient
from core.logger import DbliftLogger
from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.migration import Migration
from core.migration.placeholders.placeholder_service import PlaceholderService
from core.migration.sql.sql_analyzer import SqlAnalyzer

pytestmark = [pytest.mark.unit]

# Placeholder in identifier position, both before and after adjacent identifier
# characters — the two shapes the tokenisers mangle differently.
CALLBACK_SQL = "CREATE TABLE ${callback_schema}.callback_log_${env} (id INT);"

PLACEHOLDERS = {"callback_schema": "app_schema", "env": "dev"}

# Tokenisers that strip ``$`` and pad the braces with whitespace.
MANGLING_DIALECTS = ["oracle", "sqlserver", "mysql", "postgresql"]
# Tokenisers that leave ``${...}`` intact — regression guard, must keep working.
PASSTHROUGH_DIALECTS = ["sqlite", "duckdb", "db2"]


def _engine_for(dialect: str, tmp_path: Path, placeholders=PLACEHOLDERS):
    """Build an ExecutionEngine over a mock provider for *dialect*."""
    log = Mock(spec=DbliftLogger)
    provider = Mock()
    provider.execute_statement.return_value = 1
    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=SqlAnalyzer(dialect=dialect, logger=log),
        log=log,
        placeholder_service=(
            PlaceholderService(dict(placeholders), log) if placeholders is not None else None
        ),
        config=Mock(),
    )
    return engine, provider, log


def _callback(tmp_path: Path, dialect: str, content: str = CALLBACK_SQL) -> Migration:
    path = tmp_path / f"beforeMigrate__{dialect}_setup.sql"
    path.write_text(content)
    return Migration(path, logger=Mock(spec=DbliftLogger))


def _executed(provider) -> str:
    calls = provider.execute_statement.call_args_list
    assert calls, "callback executed no statements"
    return str(calls[0][0][0])


@pytest.mark.parametrize("dialect", MANGLING_DIALECTS + PASSTHROUGH_DIALECTS)
def test_callback_placeholders_resolve_before_tokenisation(dialect, tmp_path):
    """The provider receives resolved identifiers, never tokeniser-mangled braces."""
    engine, provider, _ = _engine_for(dialect, tmp_path)
    engine.execute_callback(_callback(tmp_path, dialect))

    statement = _executed(provider)
    assert "app_schema.callback_log_dev" in statement, statement
    assert "${" not in statement, statement
    assert "{" not in statement, statement


def test_unresolved_callback_placeholder_passes_through_as_literal(tmp_path):
    """An unknown ``${...}`` stays literal, and warns exactly once.

    Pass-through (not an error) is documented behaviour.  ``exactly once``
    pins the single substitution point: substituting again per statement
    would re-warn about the same token and re-interpret ``${...}`` text that
    legitimately came out of a resolved placeholder value.
    """
    engine, provider, log = _engine_for("sqlite", tmp_path)
    callback = _callback(
        tmp_path,
        "sqlite",
        "INSERT INTO audit (note) VALUES ('${MY_PLACEHOLDER}');",
    )

    engine.execute_callback(callback)

    statement = _executed(provider)
    assert "${MY_PLACEHOLDER}" in statement, statement

    warnings = [
        call.args[0]
        for call in log.warning.call_args_list
        if call.args and "MY_PLACEHOLDER" in str(call.args[0])
    ]
    assert len(warnings) == 1, warnings


def test_callback_override_does_not_poison_the_statement_cache(tmp_path):
    """Substituted callback SQL must not be cached on ``Migration._sql_statements``.

    The immutability contract on ``parse_sql_statements``: later readers
    (checksum, info display, a second parse) must still see canonical content.
    """
    engine, _, _ = _engine_for("oracle", tmp_path)
    callback = _callback(tmp_path, "oracle")

    engine.execute_callback(callback)

    assert callback._sql_statements is None, callback._sql_statements
    assert "${callback_schema}" in callback.content
    # A later canonical parse still sees the unsubstituted source.
    assert "${callback_schema}" in callback.parse_sql_statements(dialect="sqlite")[0]


def test_callback_without_placeholder_service_leaves_content_untouched(tmp_path):
    """No placeholder service — content reaches the parser unchanged (no crash)."""
    engine, provider, _ = _engine_for("sqlite", tmp_path, placeholders=None)
    engine.execute_callback(_callback(tmp_path, "sqlite"))

    assert "${callback_schema}" in _executed(provider)


def test_sqlite_callback_side_effects_land_end_to_end(tmp_path):
    """Full ``migrate`` run: the callback's table exists and the migration ran."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "beforeMigrate__setup.sql").write_text(
        "CREATE TABLE callback_log_${env} (note TEXT);\n"
        "INSERT INTO callback_log_${env} (note) VALUES ('${env}');\n"
    )
    (migrations / "V1__app.sql").write_text("CREATE TABLE app_table (id INTEGER);")

    db_engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(db_engine, migrations_dir=migrations)
    try:
        assert client.migrate(placeholders={"env": "dev"}).success
    finally:
        client.close()

    with db_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT note FROM callback_log_dev").fetchall() == [("dev",)]
        conn.exec_driver_sql("SELECT 1 FROM app_table")
