"""Tests for the Python migration executor."""

import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.migration.executors.python_executor import (
    MigrationContext,
    PythonMigrationExecutor,
)
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration

# Track temp files created by _make_migration for session-end cleanup
_TEMP_MIGRATION_FILES: list = []


@pytest.fixture(autouse=True, scope="session")
def cleanup_temp_migration_files():
    """Clean up temp migration script files created during tests."""
    yield
    for path in _TEMP_MIGRATION_FILES:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


@pytest.fixture
def executor():
    """Create a PythonMigrationExecutor with mock dependencies."""
    return PythonMigrationExecutor(
        provider=MagicMock(),
        config=MagicMock(),
        log=MagicMock(),
    )


def _make_migration(content, suffix=".py", script_path=None):
    """Helper to create a Migration with proper Python format detection."""
    if script_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
        tmp.write(content)
        tmp.flush()
        tmp.close()
        script_path = Path(tmp.name)
        _TEMP_MIGRATION_FILES.append(script_path)
    migration = Migration(script_path=script_path)
    migration.content = content
    return migration


# ---------- MigrationContext ----------


@pytest.mark.unit
class TestMigrationContext:
    def test_db_property_with_connection_manager(self):
        provider = MagicMock()
        provider.connection_manager.database = "test_db"
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.db == "test_db"

    def test_db_property_without_connection_manager(self):
        provider = MagicMock(spec=[])  # no attributes
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.db is None

    def test_raw_client_property_with_connection_manager(self):
        provider = MagicMock()
        provider.connection_manager.client = "cosmos_client"
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.raw_client == "cosmos_client"

    def test_raw_client_property_without_connection_manager(self):
        provider = MagicMock(spec=[])
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.raw_client is None

    def test_dry_run_default_false(self):
        ctx = MigrationContext(provider=MagicMock(), log=MagicMock())
        assert ctx.dry_run is False

    def test_dry_run_explicit_true(self):
        ctx = MigrationContext(provider=MagicMock(), log=MagicMock(), dry_run=True)
        assert ctx.dry_run is True

    def test_execute_rejects_non_string_with_cosmos_hint(self):
        ctx = MigrationContext(provider=MagicMock(), log=MagicMock())

        with pytest.raises(TypeError) as exc:
            ctx.execute({"op": "create_container", "name": "users"})

        message = str(exc.value)
        assert "context.execute() expects a SQL string" in message
        assert "context.db" in message
        assert "context.raw_client" in message


# ---------- can_execute ----------


@pytest.mark.unit
class TestCanExecute:
    def test_python_format_returns_true(self, executor):
        migration = _make_migration("def migrate(context): pass")
        assert migration.format == MigrationFormat.PYTHON
        assert executor.can_execute(migration) is True

    def test_sql_format_returns_false(self, executor):
        tmp = tempfile.NamedTemporaryFile(suffix=".sql", mode="w", delete=False)
        tmp.write("SELECT 1;")
        tmp.flush()
        tmp.close()
        migration = Migration(script_path=Path(tmp.name))
        migration.content = "SELECT 1;"
        assert executor.can_execute(migration) is False


# ---------- validate_migration ----------


@pytest.mark.unit
class TestValidateMigration:
    def test_valid_script(self, executor):
        migration = _make_migration("def migrate(context):\n    pass\n")
        is_valid, errors = executor.validate_migration(migration)
        assert is_valid is True
        assert errors == []

    def test_empty_content_v1(self, executor):
        migration = _make_migration("")
        is_valid, errors = executor.validate_migration(migration)
        assert is_valid is False
        assert len(errors) == 1
        assert "empty" in errors[0].lower() or "not loaded" in errors[0].lower()

    def test_whitespace_only_v1(self, executor):
        migration = _make_migration("   \n  \n  ")
        is_valid, errors = executor.validate_migration(migration)
        assert is_valid is False
        assert len(errors) == 1

    def test_none_content_v1(self, executor):
        migration = _make_migration("placeholder")
        migration.content = None
        is_valid, errors = executor.validate_migration(migration)
        assert is_valid is False

    def test_missing_migrate_function_v2(self, executor):
        migration = _make_migration("def run(context):\n    pass\n")
        is_valid, errors = executor.validate_migration(migration)
        assert is_valid is False
        assert any("migrate" in e.lower() for e in errors)

    def test_syntax_error_v3(self, executor):
        migration = _make_migration("def migrate(context)\n    pass\n")  # missing colon
        is_valid, errors = executor.validate_migration(migration)
        assert is_valid is False
        assert any("syntaxe" in e.lower() or "syntax" in e.lower() for e in errors)

    def test_multiple_errors_v2_and_v3(self, executor):
        # No migrate function AND syntax error
        migration = _make_migration("def run(context)\n    pass\n")
        is_valid, errors = executor.validate_migration(migration)
        assert is_valid is False
        assert len(errors) == 2


# ---------- execute_migration ----------


@pytest.mark.unit
class TestExecuteMigration:
    def test_successful_execution(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                context.log.info("migrating")
        """)
        migration = _make_migration(content)
        result = executor.execute_migration(migration)
        assert result.success is True
        assert result.statements_executed == 1
        assert result.execution_time_ms >= 0
        assert result.output is None

    def test_dry_run_true(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                assert context.dry_run is True
        """)
        migration = _make_migration(content)
        result = executor.execute_migration(migration, dry_run=True)
        assert result.success is True
        assert result.statements_executed == 1
        assert result.output is not None
        assert "DRY-RUN" in result.output

    def test_dry_run_false(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                assert context.dry_run is False
        """)
        migration = _make_migration(content)
        result = executor.execute_migration(migration, dry_run=False)
        assert result.success is True

    def test_exception_in_script(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                raise RuntimeError("boom")
        """)
        migration = _make_migration(content)
        result = executor.execute_migration(migration)
        assert result.success is False
        assert "RuntimeError" in result.error
        assert "boom" in result.error
        assert result.statements_executed == 0
        executor.log.error.assert_called_once()

    def test_script_path_none(self, executor):
        migration = _make_migration("def migrate(context): pass")
        migration.path = None
        result = executor.execute_migration(migration)
        assert result.success is False
        assert "no file path" in result.error.lower() or "script_path" in result.error.lower()

    def test_context_receives_provider(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                # Just access provider to prove it's there
                assert context.provider is not None
        """)
        migration = _make_migration(content)
        result = executor.execute_migration(migration)
        assert result.success is True


# ---------- supports_rollback ----------


@pytest.mark.unit
class TestSupportsRollback:
    def test_with_undo_function(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                pass
            def undo(context):
                pass
        """)
        migration = _make_migration(content)
        assert executor.supports_rollback(migration) is True

    def test_without_undo_function(self, executor):
        content = "def migrate(context):\n    pass\n"
        migration = _make_migration(content)
        assert executor.supports_rollback(migration) is False

    def test_none_content(self, executor):
        migration = _make_migration("placeholder")
        migration.content = None
        assert executor.supports_rollback(migration) is False


# ---------- rollback_migration ----------


@pytest.mark.unit
class TestRollbackMigration:
    def test_successful_rollback(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                pass
            def undo(context):
                context.log.info("rolling back")
        """)
        migration = _make_migration(content)
        result = executor.rollback_migration(migration)
        assert result.success is True
        assert result.statements_executed == 1

    def test_rollback_no_undo_returns_failed_result(self, executor):
        """When no undo() function is defined, returns a failed result instead of raising (LSP-01)."""
        content = "def migrate(context):\n    pass\n"
        migration = _make_migration(content)
        from core.migration.executors.base_executor import MigrationExecutionResult

        result = executor.rollback_migration(migration)
        assert isinstance(result, MigrationExecutionResult)
        assert result.success is False
        assert "undo" in result.error

    def test_rollback_exception_in_script(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                pass
            def undo(context):
                raise ValueError("undo failed")
        """)
        migration = _make_migration(content)
        result = executor.rollback_migration(migration)
        assert result.success is False
        assert "ValueError" in result.error
        assert "undo failed" in result.error

    def test_rollback_script_path_none(self, executor):
        content = textwrap.dedent("""\
            def migrate(context):
                pass
            def undo(context):
                pass
        """)
        migration = _make_migration(content)
        migration.path = None
        result = executor.rollback_migration(migration)
        assert result.success is False
        assert "no file path" in result.error.lower()


# ---------- get_supported_formats ----------


@pytest.mark.unit
class TestGetSupportedFormats:
    def test_returns_python(self, executor):
        assert executor.get_supported_formats() == [MigrationFormat.PYTHON]


@pytest.mark.unit
class TestBug03MigrationContextExecute:
    """BUG-03: MigrationContext.execute() convenience shortcut for context.provider.execute_statement."""

    def test_execute_without_params_calls_provider(self):
        provider = MagicMock()
        provider.execute_statement.return_value = 1
        ctx = MigrationContext(provider=provider, log=MagicMock())

        rc = ctx.execute("ALTER TABLE users ADD COLUMN foo VARCHAR(255)")

        provider.execute_statement.assert_called_once_with(
            "ALTER TABLE users ADD COLUMN foo VARCHAR(255)"
        )
        assert rc == 1

    def test_execute_with_params_forwards_them(self):
        provider = MagicMock()
        provider.execute_statement.return_value = 3
        ctx = MigrationContext(provider=provider, log=MagicMock())

        rc = ctx.execute("UPDATE users SET x = ? WHERE id = ?", [42, 7])

        provider.execute_statement.assert_called_once_with(
            "UPDATE users SET x = ? WHERE id = ?", params=[42, 7]
        )
        assert rc == 3
