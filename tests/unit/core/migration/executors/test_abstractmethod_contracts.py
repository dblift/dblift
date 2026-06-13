"""Tests vérifiant les contrats @abstractmethod dans BaseMigrationExecutor et OutputFormatter."""

from abc import ABC
from unittest.mock import MagicMock

import pytest

from core.migration.executors.base_executor import BaseMigrationExecutor
from core.migration.executors.python_executor import PythonMigrationExecutor
from core.migration.executors.sql_executor import SqlMigrationExecutor
from core.migration.migration import Migration
from core.sql_validator.linting.formatters import OutputFormatter


@pytest.mark.unit
class TestOutputFormatterABC:
    """Vérifie que OutputFormatter est une classe abstraite."""

    def test_output_formatter_is_abc(self):
        """OutputFormatter doit hériter de ABC."""
        assert issubclass(OutputFormatter, ABC)

    def test_output_formatter_cannot_be_instantiated(self):
        """OutputFormatter ne peut pas être instancié directement."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            OutputFormatter()

    def test_format_is_abstract(self):
        """format() doit être dans les méthodes abstraites."""
        assert "format" in OutputFormatter.__abstractmethods__

    def test_concrete_subclass_can_be_instantiated(self):
        """Une sous-classe qui implémente format() peut être instanciée."""
        from core.sql_validator.linting.formatters import ConsoleFormatter

        formatter = ConsoleFormatter()
        assert isinstance(formatter, OutputFormatter)


@pytest.mark.unit
class TestBaseMigrationExecutorRollbackAbstract:
    """Vérifie que rollback_migration est abstraite dans BaseMigrationExecutor."""

    def test_rollback_migration_is_not_abstract(self):
        """rollback_migration ne doit pas être abstraite — elle a une implémentation par défaut (LSP-01)."""
        assert "rollback_migration" not in BaseMigrationExecutor.__abstractmethods__

    def test_sql_executor_implements_rollback_migration(self):
        """SqlMigrationExecutor doit implémenter rollback_migration (AC#3)."""
        assert "rollback_migration" in SqlMigrationExecutor.__dict__

    def test_python_executor_implements_rollback_migration(self):
        """PythonMigrationExecutor doit implémenter rollback_migration."""
        assert "rollback_migration" in PythonMigrationExecutor.__dict__

    def test_base_executor_cannot_be_instantiated(self):
        """BaseMigrationExecutor ne peut pas être instancié directement."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseMigrationExecutor(MagicMock(), MagicMock(), MagicMock())  # type: ignore[abstract]

    def test_subclass_without_rollback_can_be_instantiated(self):
        """Une sous-classe sans rollback_migration peut être instanciée et hérite du comportement par défaut (LSP-01)."""

        class PartialExecutor(BaseMigrationExecutor):
            def can_execute(self, migration):
                return True

            def execute_migration(self, migration, dry_run=False, **kwargs):
                pass

            def validate_migration(self, migration):
                return True, []

        executor = PartialExecutor(MagicMock(), MagicMock(), MagicMock())
        migration = MagicMock(spec=Migration)
        result = executor.rollback_migration(migration)
        assert result.success is False
        assert "does not support rollback" in result.error

    def test_sql_executor_rollback_returns_failed_result(self):
        """SqlMigrationExecutor.rollback_migration() doit retourner un résultat échec (LSP-01)."""
        mock_provider = MagicMock()
        mock_config = MagicMock()
        mock_log = MagicMock()
        executor = SqlMigrationExecutor(mock_provider, mock_config, mock_log)
        migration = MagicMock(spec=Migration)
        from core.migration.executors.base_executor import MigrationExecutionResult

        result = executor.rollback_migration(migration)
        assert isinstance(result, MigrationExecutionResult)
        assert result.success is False
        assert "programmatic rollback" in result.error
