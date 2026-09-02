"""Regression tests for failed-history persistence operator signals."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import MigrationType


def _engine():
    engine = ExecutionEngine.__new__(ExecutionEngine)
    engine.log = MagicMock()
    engine.provider = MagicMock()
    engine.provider.rollback_transaction = MagicMock()
    engine.provider.begin_transaction = MagicMock()
    engine.provider.commit_transaction = MagicMock()
    engine.history_manager = MagicMock()
    return engine


def _migration():
    migration = MagicMock()
    migration.script_name = "V1__fail.sql"
    migration.version = "1"
    migration.description = "fail"
    migration.type = MigrationType.SQL
    migration.checksum = 123
    return migration


@pytest.mark.unit
def test_sql_failure_marks_failed_history_persisted_true():
    engine = _engine()
    result = MigrateResult()

    engine._handle_statement_failure(_migration(), RuntimeError("boom"), 0, 12, result)

    assert result.failed_history_persisted is True


@pytest.mark.unit
def test_sql_failure_marks_failed_history_persisted_false_when_history_write_fails():
    engine = _engine()
    engine.history_manager.record_migration.side_effect = RuntimeError("history down")
    result = MigrateResult()

    engine._handle_statement_failure(_migration(), RuntimeError("boom"), 0, 12, result)

    assert result.failed_history_persisted is False
    assert any("not persisted to history" in warning for warning in result.warnings)
