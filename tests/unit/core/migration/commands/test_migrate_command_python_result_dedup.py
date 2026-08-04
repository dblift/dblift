"""Regression test for issue #835.

``migrate()``'s ``result.migrations_applied`` contained a duplicate entry for
a Python migration's version (e.g. ``['1', '2', '2']`` for a SQL migration
"1" followed by a Python migration "2"). Execution itself was correct — this
was a result-payload construction bug.

Root cause: ``ExecutionEngine._execute_via_factory`` (the non-SQL/Python
execution path) records a ``MigrationInfo`` into the result on success, and
``MigrateCommand._execute_single_migration`` *also* unconditionally records a
``MigrationInfo`` for every successfully executed migration. The SQL
execution path never appends to the result internally on success (only
``_handle_statement_failure`` does, for failures), so only Python migrations
were recorded twice.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.logger.results import MigrateResult
from core.migration.commands.migrate_command import MigrateCommand
from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration, MigrationType
from db.provider_interfaces import TransactionalProvider


def _make_engine():
    provider = MagicMock()
    provider.__class__ = TransactionalProvider
    provider.supports_transactions.return_value = True
    provider.supports_transactional_ddl.return_value = True
    provider.connection = MagicMock()
    provider.connection.getAutoCommit.return_value = False
    provider.connection.isClosed.return_value = False

    sql_analyzer = MagicMock()
    sql_analyzer.dialect = "postgresql"

    config = MagicMock()
    config.database.type.value = "postgresql"
    config.database.url = "postgresql://host/db"

    history_manager = MagicMock()

    return ExecutionEngine(
        provider=provider,
        sql_analyzer=sql_analyzer,
        log=MagicMock(),
        config=config,
        history_manager=history_manager,
    )


def _make_sql_migration():
    m = MagicMock(spec=Migration)
    m.format = MigrationFormat.SQL
    m.content = "SELECT 1;"
    m.script_name = "V1__init.sql"
    m.version = "1"
    m.description = "init"
    m.checksum = 111
    m.type = MigrationType.SQL
    return m


def _make_python_migration():
    m = MagicMock(spec=Migration)
    m.format = MigrationFormat.PYTHON
    m.script_name = "V2__seed.py"
    m.version = "2"
    m.description = "seed data"
    m.checksum = 222
    m.type = MigrationType.PYTHON
    return m


def _make_command(execution_engine):
    cmd = MigrateCommand.__new__(MigrateCommand)
    cmd.execution_engine = execution_engine
    cmd.log = MagicMock()
    cmd.journal = None
    cmd._execute_callbacks = MagicMock()
    return cmd


class TestMigrateResultNoDuplicateForPythonMigration(unittest.TestCase):
    def test_migrations_applied_has_no_duplicate_for_python_migration(self):
        engine = _make_engine()
        cmd = _make_command(engine)
        result = MigrateResult()

        sql_migration = _make_sql_migration()
        python_migration = _make_python_migration()

        policy = MagicMock()
        policy.transactional = True
        policy.autocommit_required = False
        policy.unsupported_mixed_mode = False
        engine.transaction_policy = MagicMock()
        engine.transaction_policy.decide.return_value = policy

        exec_result = MagicMock()
        exec_result.success = True
        exec_result.execution_time_ms = 5
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result

        with patch("core.migration.commands.migrate_command._emit_script_event"):
            with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
                with patch.object(engine, "_classify_execution_statements", return_value=[]):
                    with patch.object(engine, "_prepare_transaction", return_value=True):
                        with patch.object(engine, "_execute_statements", return_value=True):
                            with patch.object(engine, "_record_migration_history"):
                                with patch.object(engine, "_commit_and_verify"):
                                    success_sql = cmd._execute_single_migration(
                                        sql_migration,
                                        Path("/migrations"),
                                        True,
                                        None,
                                        None,
                                        result,
                                    )
                                    success_py = cmd._execute_single_migration(
                                        python_migration,
                                        Path("/migrations"),
                                        True,
                                        None,
                                        None,
                                        result,
                                    )

        self.assertTrue(success_sql)
        self.assertTrue(success_py)

        applied = result.migrations_applied
        self.assertEqual(applied, ["1", "2"], f"expected no duplicates, got {applied}")


if __name__ == "__main__":
    unittest.main()
