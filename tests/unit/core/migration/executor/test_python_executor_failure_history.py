"""BUG-04 regression: Python executor failures leave a FAILED history row.

Before the fix, the SQL execution path wrote a FAILED row to
``dblift_schema_history`` via ``_handle_statement_failure`` so that
``repair`` could detect and clear it. The Python path
(``_execute_via_factory``) rolled back the transaction, appended a
FAILED ``MigrationInfo`` to the in-memory result, and returned — but
never called ``history_manager.record_migration(success=False)``. The
outcome was a stuck Pending migration that ``repair`` could not see.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executors.base_executor import MigrationExecutionResult
from dblift.core.migration.formats import MigrationFormat


def _make_engine():
    engine = ExecutionEngine.__new__(ExecutionEngine)
    engine.log = MagicMock()
    engine.provider = MagicMock()
    # Mark as TransactionalProvider so the code path executes begin/commit.
    from dblift.db.provider_interfaces import TransactionalProvider

    engine.provider.__class__ = type("FakeProvider", (TransactionalProvider,), {})
    engine.provider.begin_transaction = MagicMock(return_value=True)
    engine.provider.commit_transaction = MagicMock()
    engine.provider.rollback_transaction = MagicMock()
    engine.history_manager = MagicMock()
    engine.executor_factory = MagicMock()
    engine._prepare_transaction = MagicMock(return_value=True)
    return engine


def _fake_migration():
    m = MagicMock()
    m.script_name = "V10__python.py"
    m.version = "10"
    m.description = "python migration"
    m.format = MigrationFormat.PYTHON
    m.checksum = 0
    return m


@pytest.mark.unit
class TestPythonExecutorFailureWritesHistory:
    def test_failed_python_migration_records_failed_history_row(self):
        engine = _make_engine()
        migration = _fake_migration()
        engine.executor_factory.execute.return_value = MigrationExecutionResult(
            success=False,
            migration=migration,
            execution_time_ms=42,
            error="AttributeError: 'MigrationContext' object has no attribute 'cursor'",
        )
        result = MigrateResult()

        engine._execute_via_factory(migration, result)

        engine.history_manager.record_migration.assert_called_once()
        args, kwargs = engine.history_manager.record_migration.call_args
        assert kwargs.get("success") is False or (len(args) >= 2 and args[1] is False)
        assert kwargs.get("execution_time") == 42 or (len(args) >= 3 and args[2] == 42)
        assert result.failed_history_persisted is True

    def test_successful_python_migration_records_success_history_row(self):
        engine = _make_engine()
        migration = _fake_migration()
        engine.executor_factory.execute.return_value = MigrationExecutionResult(
            success=True,
            migration=migration,
            execution_time_ms=12,
        )
        result = MigrateResult()

        engine._execute_via_factory(migration, result)

        engine.history_manager.record_migration.assert_called_once()
        _, kwargs = engine.history_manager.record_migration.call_args
        assert kwargs.get("success") is True

    def test_history_write_failure_on_failed_path_is_swallowed(self):
        """History write failure must not mask the original migration failure."""
        engine = _make_engine()
        migration = _fake_migration()
        engine.executor_factory.execute.return_value = MigrationExecutionResult(
            success=False,
            migration=migration,
            execution_time_ms=7,
            error="boom",
        )
        engine.history_manager.record_migration.side_effect = RuntimeError("history table missing")
        result = MigrateResult()

        engine._execute_via_factory(migration, result)

        # record_migration was attempted once; the RuntimeError did NOT bubble out.
        engine.history_manager.record_migration.assert_called_once()
        assert result.error_message == "boom"
        assert result.failed_history_persisted is False
        assert any("not persisted to history" in warning for warning in result.warnings)
