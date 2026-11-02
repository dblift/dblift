"""A command's engine error reads the same everywhere: engine message, no driver wrapper.

SQLAlchemy wraps a DBAPI error as ``(module.Class) <driver text>\\n[SQL: ...]\\n(Background on
this error at: <link>)``. The message of the engine is what the user needs; the wrapper, the
statement block (dblift's own statement) and the link are noise.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from dblift.core.logger.results import MigrateResult
from dblift.core.migration.commands._script_runner import ScriptRunner
from dblift.core.migration.commands.base_command import BaseCommand
from dblift.core.migration.commands.migrate_command import MIGRATE_POLICY
from dblift.core.migration.commands.undo_command import UNDO_POLICY
from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations

_NOISE = ("(pymysql.err", "(ibm_db_dbi", "[SQL:", "sqlalche.me", "Background on this error")


def _driver_error(module: str, name: str, *args) -> Exception:
    return type(name, (Exception,), {"__module__": module})(*args)


def _mysql_access_denied() -> Exception:
    orig = _driver_error(
        "pymysql.err",
        "OperationalError",
        1044,
        "Access denied for user 'q5d_u'@'%' to database 'q5d_db'",
    )
    return OperationalError("SHOW EVENTS FROM `q5d_db`", None, orig)


def _db2_undefined_name() -> Exception:
    orig = _driver_error(
        "ibm_db_dbi",
        "ProgrammingError",
        "ibm_db_dbi::ProgrammingError: Statement Execute Failed: [IBM][CLI Driver][DB2/LINUXX8664] "
        'SQL0204N  "r2_eng_d2.DBLIFT_SCHEMA_HISTORY" is an undefined name.  '
        "SQLSTATE=42704 SQLCODE=-204",
    )
    statement = (
        '\n            SELECT SCRIPT, INSTALLED_RANK FROM "r2_eng_d2"."DBLIFT_SCHEMA_HISTORY"'
        "\n            ORDER BY INSTALLED_RANK\n            "
    )
    return ProgrammingError(statement, None, orig)


def _db2_lock_timeout() -> Exception:
    orig = _driver_error(
        "ibm_db_dbi",
        "Error",
        "ibm_db_dbi::Error: [IBM][CLI Driver][DB2/LINUXX8664] SQL0911N  The current transaction "
        'has been rolled back because of a deadlock or timeout.  Reason code "2".  '
        "SQLSTATE=40001 SQLCODE=-911",
    )
    return DBAPIError("INSERT INTO DBLIFT_SCHEMA_HISTORY VALUES (?)", (1,), orig)


ENGINE_ERRORS = [
    pytest.param(_mysql_access_denied, "Access denied for user", id="mysql-access-denied"),
    pytest.param(_db2_undefined_name, "SQL0204N", id="db2-undefined-name"),
    pytest.param(_db2_lock_timeout, "SQL0911N", id="db2-lock-timeout"),
]


def _assert_readable(text: str, engine_text: str) -> None:
    assert engine_text in text
    for noise in _NOISE:
        assert noise not in text, text


@pytest.mark.unit
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
def test_the_wrapped_errors_carry_the_noise_the_tests_look_for(make_error, engine_text):
    """Guard the fixtures: the raw text has the wrapper, so the assertions can fail."""
    raw = str(make_error())
    assert "[SQL:" in raw and "sqlalche.me" in raw


@pytest.mark.unit
@pytest.mark.parametrize("prefix", ["Info operation failed", "Clean operation failed"])
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
def test_lifecycle_error_is_the_engine_message(prefix, make_error, engine_text):
    command = BaseCommand.__new__(BaseCommand)
    command.log = MagicMock()
    command._log_command_header_update = MagicMock()
    command._log_command_completion = MagicMock()
    result = SimpleNamespace(success=True, error_message="")
    result.set_error = lambda message: setattr(result, "error_message", message)

    def body() -> None:
        raise make_error()

    command._run_command_lifecycle("x", result, body, error_message_prefix=prefix)

    assert result.error_message.startswith(f"{prefix}: ")
    _assert_readable(result.error_message, engine_text)
    logged = command.log.error.call_args.args[0]
    assert logged == result.error_message


def _clean_command(provider):
    from tests.unit.core.migration.commands.test_clean_command_extended import _make_cmd

    command = _make_cmd(provider=provider)
    command._run_preflight = MagicMock()
    command._log_command_header_update = MagicMock()
    command._log_command_completion = MagicMock()
    return command


@pytest.mark.unit
@pytest.mark.parametrize("failing_step", ["validate_clean_target", "prepare_clean_target"])
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
def test_clean_target_failure_is_the_engine_message(failing_step, make_error, engine_text):
    from dblift.db.provider_interfaces import CleanTargetProvider

    provider = MagicMock(spec=CleanTargetProvider)
    provider.validate_clean_target.return_value = "public"
    getattr(provider, failing_step).side_effect = make_error()
    command = _clean_command(provider)

    result = command.execute(clean_enabled=True)

    assert result.success is False
    assert result.error_message.startswith("Clean operation failed: ")
    _assert_readable(result.error_message, engine_text)
    _assert_readable(command.log.error.call_args.args[0], engine_text)


@pytest.mark.unit
def test_mysql_event_probe_message_keeps_the_privilege_hint_and_drops_the_wrapper():
    executor = MagicMock()
    wrapped = _mysql_access_denied()
    executor.execute_query.side_effect = wrapped
    executor.get_quoted_schema_name.side_effect = lambda name: f"`{name}`"
    operations = MySqlSchemaOperations(executor, log=MagicMock())

    with pytest.raises(RuntimeError) as raised:
        operations._check_events_listable(MagicMock(), "q5d_db")

    message = str(raised.value)
    assert message.startswith("Cannot list the events in database 'q5d_db': clean needs the EVENT")
    _assert_readable(message, "Access denied for user")
    assert raised.value.__cause__ is wrapped


def _script():
    return SimpleNamespace(
        script_name="U2__orders.sql",
        version="2",
        description="orders",
        type=SimpleNamespace(value="SQL"),
    )


@pytest.mark.unit
@pytest.mark.parametrize("policy", [MIGRATE_POLICY, UNDO_POLICY], ids=["migrate", "undo"])
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
def test_script_failure_outside_the_statement_is_the_engine_message(
    policy, make_error, engine_text
):
    command = MagicMock()
    command.execution_engine.execute_migration.side_effect = make_error()
    result = MigrateResult()

    with patch("dblift.core.migration.commands._script_runner.emit_script_event"):
        ok = ScriptRunner(command, policy).run(
            _script(), result, event_data={}, on_success=MagicMock()
        )

    assert ok is False
    assert result.error_message.startswith(f"{policy.failure_prefix}: ")
    _assert_readable(result.error_message, engine_text)
    _assert_readable(command.log.error.call_args.args[0], engine_text)


def _engine(history_error: Exception):
    from tests.unit.core.migration.executor.test_execution_engine_extended import _make_engine

    engine = _make_engine(with_history=True)
    engine.history_manager.record_migration.side_effect = history_error
    return engine


@pytest.mark.unit
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
@pytest.mark.parametrize("record", ["_record_migration_history", "_record_autocommit_history"])
def test_history_write_failure_is_logged_as_the_engine_message(record, make_error, engine_text):
    from tests.unit.core.migration.executor.test_execution_engine_extended import (
        _make_sql_migration,
    )

    engine = _engine(make_error())
    method = (
        engine._record_migration_history
        if record == "_record_migration_history"
        else engine._record_autocommit_migration_history
    )

    with pytest.raises(DBAPIError):
        method(_make_sql_migration(), 5)

    _assert_readable(engine.log.error.call_args.args[0], engine_text)


@pytest.mark.unit
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
@pytest.mark.parametrize("failing", ["history", "commit"])
def test_python_migration_history_or_commit_failure_is_the_engine_message(
    failing, make_error, engine_text
):
    from tests.unit.core.migration.executor.test_execution_engine_extended import (
        _make_python_migration,
    )

    engine = _engine(make_error() if failing == "history" else RuntimeError("unused"))
    if failing == "commit":
        engine.history_manager.record_migration.side_effect = None
        engine.provider.commit_transaction.side_effect = make_error()
    exec_result = MagicMock(success=True, execution_time_ms=3)
    engine.executor_factory = MagicMock()
    engine.executor_factory.execute.return_value = exec_result
    result = MagicMock()

    with patch.object(engine, "_prepare_transaction", return_value=True):
        engine._execute_via_factory(_make_python_migration(), result)

    message = result.set_error.call_args.args[0]
    assert message.startswith("Failed to ")
    _assert_readable(message, engine_text)
    _assert_readable(engine.log.error.call_args.args[0], engine_text)


@pytest.mark.unit
def test_failing_migration_statement_keeps_naming_the_statement_and_the_engine_message():
    """Not changed: the error of a user's statement still says which one broke and why."""
    from tests.unit.core.migration.executor.test_execution_engine_extended import (
        _make_sql_migration,
    )

    orig = _driver_error(
        "psycopg.errors", "UniqueViolation", "duplicate key value violates unique constraint"
    )
    error = DBAPIError("INSERT INTO t (id) VALUES (1), (1)", None, orig)
    engine = _engine(RuntimeError("unused"))
    result = MigrateResult()

    engine._handle_statement_failure(_make_sql_migration(name="V1__bad.sql"), error, 1, 4, result)

    assert result.error_message == (
        "Failed to execute statement 2 in V1__bad.sql: "
        "duplicate key value violates unique constraint"
    )


def _plugin_operations():
    from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations
    from dblift.db.plugins.postgresql.postgresql.schema_operations import (
        PostgreSqlSchemaOperations,
    )
    from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations
    from dblift.db.plugins.sqlserver.sqlserver.schema_operations import (
        SqlServerSchemaOperations,
    )

    return [
        pytest.param(MySqlSchemaOperations, "set_current_schema", id="mysql-set-database"),
        pytest.param(MySqlSchemaOperations, "clean_schema", id="mysql-clean"),
        pytest.param(PostgreSqlSchemaOperations, "create_schema_if_not_exists", id="pg-create"),
        pytest.param(PostgreSqlSchemaOperations, "clean_schema", id="pg-clean"),
        pytest.param(SqlServerSchemaOperations, "create_schema_if_not_exists", id="mssql-create"),
        pytest.param(SqlServerSchemaOperations, "clean_schema", id="mssql-clean"),
        pytest.param(SQLiteSchemaOperations, "clean_schema", id="sqlite-clean"),
    ]


@pytest.mark.unit
@pytest.mark.parametrize("operations_class, method", _plugin_operations())
def test_schema_operation_failure_is_logged_as_the_engine_message(operations_class, method):
    executor = MagicMock()
    executor.get_quoted_schema_name.side_effect = lambda name: f'"{name}"'
    executor.get_schema_qualified_name.side_effect = lambda schema, name: f'"{schema}"."{name}"'
    for call in ("execute_query", "execute_statement", "execute_update"):
        getattr(executor, call).side_effect = _db2_lock_timeout()
    log = MagicMock()
    operations = operations_class(executor, log=log)
    connection = MagicMock()
    connection.execute.side_effect = _db2_lock_timeout()
    connection.cursor.side_effect = _db2_lock_timeout()

    try:
        getattr(operations, method)(connection, "q5d_s")
    except Exception:  # noqa: BLE001 - the failure is expected, its log line is under test
        pass

    lines = [c.args[0] for c in log.error.call_args_list + log.warning.call_args_list]
    assert lines, "the failure was not logged"
    for line in lines:
        _assert_readable(line, "SQL0911N")


@pytest.mark.unit
@pytest.mark.parametrize("failing", ["repair_checksum", "commit_transaction"])
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
def test_repair_failure_is_the_engine_message(failing, make_error, engine_text):
    from dblift.core.logger.results import RepairResult
    from dblift.db.base_provider import TransactionalProvider
    from tests.unit.core.migration.commands.test_repair_command_extended import (
        _make_cmd,
        as_actions,
    )

    provider = MagicMock()
    provider.__class__ = TransactionalProvider
    history_manager = MagicMock()
    history_manager.normalized_history_table = "dblift_schema_history"
    getattr(
        provider if failing == "commit_transaction" else history_manager, failing
    ).side_effect = make_error()
    config = MagicMock()
    config.database.schema = "public"
    config.database.type = "postgresql"
    command = _make_cmd(provider=provider, config=config, history_manager=history_manager)
    repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": 200}]
    result = RepairResult()

    with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
        command._execute_repair_loop(as_actions(repairs), result)

    assert result.error_message.startswith("Repair")
    _assert_readable(result.error_message, engine_text)


@pytest.mark.unit
@pytest.mark.parametrize("make_error, engine_text", ENGINE_ERRORS)
def test_history_commit_failure_is_logged_as_the_engine_message(make_error, engine_text):
    from dblift.core.migration.history.history_transaction import history_transaction
    from dblift.db.provider_interfaces import TransactionalProvider

    provider = MagicMock(spec=TransactionalProvider)
    provider.commit_transaction.side_effect = make_error()
    log = MagicMock()

    with pytest.raises(DBAPIError):
        with history_transaction(provider, log, "baseline"):
            pass

    _assert_readable(log.error.call_args.args[0], engine_text)
