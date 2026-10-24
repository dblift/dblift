"""The transaction-statement rule is applied where every consumer's statements are prepared.

One call at the end of ``ExecutionEngine._prepare_sql_statements`` reaches the migration run,
SQL callbacks, dry-run / ``--show-sql``, and the all-scripts preflight that runs before the first
migration does. Each test would fail if that call were removed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.commands.base_command import BaseCommand
from dblift.core.migration.executor import execution_engine
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.sql.statement_reader import StatementReader
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit

ENVELOPE = "BEGIN;\nCREATE TABLE t (a INT);\nCOMMIT;\n"
REFUSED = "CREATE TABLE t (a INT);\nCOMMIT;\nCREATE TABLE u (a INT);\n"


def _engine(dialect="sqlite"):
    provider = MagicMock()
    provider.execute_statement.return_value = 0
    log = MagicMock()
    return ExecutionEngine(provider, StatementReader(dialect=dialect, logger=log), log)


def _script(engine, content, name="V1__x.sql"):
    return make_migration(script_name=name, content=content, logger=engine.log)


def _executed(engine):
    return [c.args[0] for c in engine.provider.execute_statement.call_args_list]


def test_migration_runs_the_body_without_the_envelope():
    engine = _engine()
    migration = _script(engine, ENVELOPE)
    result = MigrateResult()

    engine.execute_migration(migration, result)

    assert [s.strip(";\n ") for s in _executed(engine)] == ["CREATE TABLE t (a INT)"]
    engine.log.warning.assert_any_call(
        "Dropped BEGIN and COMMIT from V1__x.sql: dblift runs the script in one "
        "transaction of its own"
    )


def test_migration_refused_runs_nothing():
    engine = _engine()
    result = MigrateResult()

    engine.execute_migration(_script(engine, REFUSED), result)

    assert _executed(engine) == []
    assert not result.success
    assert "V1__x.sql, line 2: COMMIT manages the transaction" in result.error_message


def test_dry_run_shows_the_statements_that_would_run():
    engine = _engine()
    statements = engine.get_executable_sql_statements(_script(engine, ENVELOPE), MigrateResult())
    assert [s.strip(";\n ") for s in statements] == ["CREATE TABLE t (a INT)"]


def test_dry_run_of_a_refused_script_reports_the_refusal():
    engine = _engine()
    result = MigrateResult()
    assert engine.get_executable_sql_statements(_script(engine, REFUSED), result) == []
    assert "COMMIT manages the transaction" in result.error_message


def test_callback_envelope_is_dropped_and_refusal_raises():
    engine = _engine()
    engine.execute_callback(_script(engine, ENVELOPE, "beforeMigrate__x.sql"))
    assert [s.strip(";\n ") for s in _executed(engine)] == ["CREATE TABLE t (a INT)"]

    refused = _engine()
    with pytest.raises(UnsupportedMetaCommandError, match="COMMIT manages the transaction"):
        refused.execute_callback(_script(refused, REFUSED, "beforeMigrate__x.sql"))
    assert _executed(refused) == []


def test_preflight_refuses_the_third_script_before_the_first_runs():
    engine = _engine()
    scripts = [
        _script(engine, "CREATE TABLE a (a INT);", "V1__a.sql"),
        _script(engine, "CREATE TABLE b (a INT);", "V2__b.sql"),
        _script(engine, REFUSED, "V3__c.sql"),
    ]
    command = SimpleNamespace(
        _capture_objects=False, execution_engine=engine, placeholder_service=None
    )

    with pytest.raises(UnsupportedMetaCommandError, match=r"V3__c\.sql, line 2: COMMIT"):
        BaseCommand._preflight_execution_sql(command, scripts)
    assert _executed(engine) == []


def _prepared(engine, content):
    """The prepared statements, or the splitter's refusal (Oracle and Db2 read a lone BEGIN as a block)."""
    try:
        return engine._prepare_sql_statements(_script(engine, content))
    except Exception as exc:  # noqa: BLE001 - the outcome itself is what is compared
        return type(exc), str(exc)


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "oracle", "sqlserver", "db2"])
@pytest.mark.parametrize("content", [ENVELOPE, REFUSED, "COMMIT;\nROLLBACK;\nEND;\n"])
def test_other_dialects_prepare_the_same_statements_with_or_without_the_rule(
    dialect, content, monkeypatch
):
    engine = _engine(dialect)
    with_rule = _prepared(engine, content)
    monkeypatch.setattr(
        execution_engine, "neutralise_transaction_statements", lambda statements, **_: statements
    )
    assert _prepared(engine, content) == with_rule
