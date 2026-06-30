"""Tests for core/migration/executors/sql_executor.py."""

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock, patch


def _make_executor():
    from core.migration.executors.sql_executor import SqlMigrationExecutor

    provider = MagicMock()
    config = MagicMock()
    config.database.type = "postgresql"
    log = MagicMock()
    sql_analyzer = MagicMock()
    sql_analyzer.dialect = "postgresql"
    return (
        SqlMigrationExecutor(provider=provider, config=config, log=log, sql_analyzer=sql_analyzer),
        provider,
        config,
        log,
        sql_analyzer,
    )


def _make_migration(content="SELECT 1;", fmt="SQL"):
    import tempfile
    from pathlib import Path

    from core.migration.formats.migration_format import MigrationFormat

    f = tempfile.NamedTemporaryFile(suffix=".sql", delete=False, mode="w")
    f.write(content)
    f.close()
    m = MagicMock()
    m.path = Path(f.name)
    m.format = MigrationFormat.SQL
    m.version = "1"
    m.description = "test"
    m.content = content
    m.parse_sql_statements.return_value = ["SELECT 1"]
    return m


class TestSqlMigrationExecutorInit(unittest.TestCase):
    def test_init_stores_components(self):
        exec_, provider, config, log, sa = _make_executor()
        self.assertIs(exec_.provider, provider)
        self.assertIs(exec_.sql_analyzer, sa)

    def test_init_creates_default_sql_analyzer(self):
        from core.migration.executors.sql_executor import SqlMigrationExecutor

        provider = MagicMock()
        config = MagicMock()
        config.database.type = "postgresql"
        log = MagicMock()
        # SqlAnalyzer is imported inline — patch at its source module
        with patch("core.migration.sql.sql_analyzer.SqlAnalyzer") as MockSA:
            MockSA.return_value = MagicMock()
            exec_ = SqlMigrationExecutor(provider=provider, config=config, log=log)
        self.assertIsNotNone(exec_.sql_analyzer)

    def test_default_analyzer_uses_config_database_type(self):
        """When config supplies a dialect it is passed through to SqlAnalyzer."""
        from core.migration.executors.sql_executor import SqlMigrationExecutor

        provider = MagicMock()
        config = MagicMock()
        config.database.type = "mysql"
        log = MagicMock()
        with patch("core.migration.sql.sql_analyzer.SqlAnalyzer") as MockSA:
            MockSA.return_value = MagicMock()
            SqlMigrationExecutor(provider=provider, config=config, log=log)
        _, kwargs = MockSA.call_args
        self.assertEqual(kwargs.get("dialect"), "mysql")

    def test_default_analyzer_no_config_uses_registry_default(self):
        """ADR-26 E5: with no config, the dialect comes from the registry,
        not a hardcoded ``"postgresql"`` literal.

        It must equal the shared registry-derived splitter default so the
        no-dialect path is consistent across the codebase.
        """
        from core.migration.executors.sql_executor import SqlMigrationExecutor
        from core.migration.migration import _default_splitter_dialect
        from db.provider_registry import ProviderRegistry

        provider = MagicMock()
        log = MagicMock()
        with patch("core.migration.sql.sql_analyzer.SqlAnalyzer") as MockSA:
            MockSA.return_value = MagicMock()
            SqlMigrationExecutor(provider=provider, config=None, log=log)
        _, kwargs = MockSA.call_args
        dialect = kwargs.get("dialect")
        self.assertEqual(dialect, _default_splitter_dialect())
        self.assertEqual(ProviderRegistry.canonical_dialect_name(dialect), dialect)
        self.assertTrue(ProviderRegistry.is_native_dialect(dialect))


class TestSqlMigrationExecutorCanExecute(unittest.TestCase):
    def test_sql_format_true(self):
        from core.migration.formats.migration_format import MigrationFormat

        exec_, *_ = _make_executor()
        m = MagicMock()
        m.format = MigrationFormat.SQL
        self.assertTrue(exec_.can_execute(m))

    def test_python_format_false(self):
        from core.migration.formats.migration_format import MigrationFormat

        exec_, *_ = _make_executor()
        m = MagicMock()
        m.format = MigrationFormat.PYTHON
        self.assertFalse(exec_.can_execute(m))

    def test_no_format_checks_extension(self):
        exec_, *_ = _make_executor()
        m = MagicMock(spec=["path"])
        m.path = Path("/tmp/migration.sql")
        self.assertTrue(exec_.can_execute(m))

    def test_no_format_python_extension(self):
        exec_, *_ = _make_executor()
        m = MagicMock(spec=["path"])
        m.path = Path("/tmp/migration.py")
        self.assertFalse(exec_.can_execute(m))

    def test_no_format_no_path_defaults_true(self):
        exec_, *_ = _make_executor()
        m = MagicMock(spec=[])  # no format, no path
        self.assertTrue(exec_.can_execute(m))


class TestSqlMigrationExecutorGetFormats(unittest.TestCase):
    def test_returns_sql_format(self):
        from core.migration.formats.migration_format import MigrationFormat

        exec_, *_ = _make_executor()
        formats = exec_.get_supported_formats()
        self.assertIn(MigrationFormat.SQL, formats)


class TestSqlMigrationExecutorExecute(unittest.TestCase):
    def test_dry_run_success(self):
        exec_, *_ = _make_executor()
        m = _make_migration()
        exec_.validate_migration = MagicMock(return_value=(True, []))
        result = exec_.execute_migration(m, dry_run=True)
        self.assertTrue(result.success)
        self.assertIn("DRY-RUN", result.output)

    def test_validation_failure_returns_failure(self):
        exec_, *_ = _make_executor()
        m = _make_migration()
        exec_.validate_migration = MagicMock(return_value=(False, ["invalid SQL"]))
        result = exec_.execute_migration(m, dry_run=False)
        self.assertFalse(result.success)
        self.assertIn("invalid SQL", result.error)

    def test_execute_via_provider(self):
        exec_, provider, *_ = _make_executor()
        m = _make_migration()
        exec_.validate_migration = MagicMock(return_value=(True, []))
        exec_.sql_execution_service = None
        exec_._execute_via_provider = MagicMock()
        result = exec_.execute_migration(m, dry_run=False)
        exec_._execute_via_provider.assert_called_once()

    def test_execute_exception_returns_failure(self):
        exec_, *_ = _make_executor()
        m = _make_migration()
        exec_.validate_migration = MagicMock(return_value=(True, []))
        exec_.sql_execution_service = None
        exec_._execute_via_provider = MagicMock(side_effect=Exception("DB error"))
        result = exec_.execute_migration(m, dry_run=False)
        self.assertFalse(result.success)
