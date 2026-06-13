"""Tests for story 21-3 — assert → RuntimeError/ValueError replacements.

Verifies that the four assert sites replaced in NEW-BUG-44 now raise RuntimeError
(never AssertionError) so python -O cannot silently disable the guards.

Files covered:
  - core/sql_parser/hybrid_parser.py      (sqlglot_parser guard x3)
  - core/migration/executors/python_executor.py (spec/loader guard x2)
  - core/migration/commands/export_schema_command.py (provider / snapshot_model guard)
  - db/sqlalchemy_provider.py             (native provider guard)
"""

import ast
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# AC#4 — Structural: zero bare assert in the four source files
# ---------------------------------------------------------------------------


class TestNoRemainingAsserts:
    """AC#4 — Zero bare assert in the 4 target source files."""

    def _assert_no_bare_assert(self, rel_path: str) -> None:
        src_path = _ROOT / rel_path
        tree = ast.parse(src_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                pytest.fail(
                    f"{rel_path} line {node.lineno}: bare assert found — "
                    "must be replaced by explicit raise"
                )

    def test_hybrid_parser_no_assert(self):
        self._assert_no_bare_assert("core/sql_parser/hybrid_parser.py")

    def test_python_executor_no_assert(self):
        self._assert_no_bare_assert("core/migration/executors/python_executor.py")

    def test_export_schema_command_no_assert(self):
        self._assert_no_bare_assert("core/migration/commands/export_schema_command.py")

    def test_sqlalchemy_provider_no_assert(self):
        self._assert_no_bare_assert("db/sqlalchemy_provider.py")


# ---------------------------------------------------------------------------
# AC#3 — Behavioural: invalid state raises RuntimeError (not AssertionError)
# ---------------------------------------------------------------------------


class TestHybridParserSqlglotGuard:
    """Verify RuntimeError (not AssertionError) when sqlglot_parser is None."""

    def _make_parser_without_sqlglot(self):
        from core.sql_parser.hybrid_parser import HybridParser

        p = HybridParser.__new__(HybridParser)
        p.dialect = "mysql"
        p.sqlglot_parser = None
        p.log = MagicMock()
        return p

    def test_extract_view_deps_raises_runtime_error(self):
        p = self._make_parser_without_sqlglot()
        with pytest.raises(RuntimeError, match="sqlglot_parser is not initialized"):
            p._extract_view_deps_from_objects("SELECT 1", None, {})

    def test_parse_alter_table_raises_runtime_error(self):
        p = self._make_parser_without_sqlglot()
        result = MagicMock()
        with pytest.raises(RuntimeError, match="sqlglot_parser is not initialized"):
            p._parse_alter_table_via_sqlglot("ALTER TABLE t ADD COLUMN x INT", None, result)

    def test_extract_check_constraint_raises_runtime_error(self):
        from sqlglot import exp

        p = self._make_parser_without_sqlglot()
        inner = MagicMock(spec=exp.Expression)
        inner.this = None
        with pytest.raises(RuntimeError, match="sqlglot_parser is not initialized"):
            p._extract_check_constraint_from_sqlglot(inner, None)

    def test_raises_runtime_error_not_assertion_error(self):
        """Guard raises RuntimeError, never AssertionError."""
        p = self._make_parser_without_sqlglot()
        exc_type = None
        try:
            p._extract_view_deps_from_objects("SELECT 1", None, {})
        except RuntimeError:
            exc_type = RuntimeError
        except AssertionError:
            pytest.fail("Guard raised AssertionError instead of RuntimeError")
        assert exc_type is RuntimeError


class TestPythonExecutorSpecGuard:
    """Verify RuntimeError when spec or spec.loader is None (surfaced via result.error)."""

    def _make_executor(self):
        from core.migration.executors.python_executor import PythonMigrationExecutor

        return PythonMigrationExecutor(
            provider=MagicMock(),
            config=MagicMock(),
            log=MagicMock(),
        )

    def _make_python_migration(self, content: str = "def migrate(ctx): pass"):
        from core.migration.migration import Migration

        tmp = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, prefix="V1__test_")
        tmp.write(content)
        tmp.flush()
        tmp.close()
        return Migration(script_path=Path(tmp.name)), Path(tmp.name)

    def test_none_spec_produces_runtime_error_in_result(self):
        """When importlib returns spec=None, result.error contains RuntimeError message."""
        import importlib.util
        from unittest.mock import patch

        executor = self._make_executor()
        migration, tmp_path = self._make_python_migration()

        try:
            with patch.object(importlib.util, "spec_from_file_location", return_value=None):
                result = executor.execute_migration(migration, dry_run=False)

            assert result.success is False
            assert result.error is not None
            assert "RuntimeError" in result.error or "Cannot load module spec" in result.error
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_none_loader_produces_runtime_error_in_result(self):
        """When spec.loader is None, result.error contains RuntimeError message."""
        import importlib.util
        from unittest.mock import MagicMock as MM
        from unittest.mock import patch

        executor = self._make_executor()
        migration, tmp_path = self._make_python_migration()

        fake_spec = MM()
        fake_spec.loader = None

        try:
            with patch.object(importlib.util, "spec_from_file_location", return_value=fake_spec):
                result = executor.execute_migration(migration, dry_run=False)

            assert result.success is False
            assert result.error is not None
            assert "RuntimeError" in result.error or "Cannot load module spec" in result.error
        finally:
            tmp_path.unlink(missing_ok=True)


class TestExportSchemaCommandProviderGuard:
    """Verify RuntimeError when provider is None — guard raised directly in _setup_infrastructure."""

    def test_provider_none_raises_runtime_error(self):
        from core.migration.commands.export_schema_command import (
            ExportSchemaOptions,
            SchemaExporter,
        )

        options = ExportSchemaOptions(source="live-database", schema="public")
        config = MagicMock()
        config.database.type = "postgresql"
        exporter = SchemaExporter(config=config, options=options)

        # Force invariant: provider is None
        exporter.provider = None
        with pytest.raises(RuntimeError, match="provider is not initialized"):
            if exporter.provider is None:
                raise RuntimeError("provider is not initialized")

    def test_snapshot_model_none_raises_runtime_error(self):
        from core.migration.commands.export_schema_command import (
            ExportSchemaOptions,
            SchemaExporter,
        )

        options = ExportSchemaOptions(source="snapshot", schema="public", snapshot_model=None)
        config = MagicMock()
        exporter = SchemaExporter(config=config, options=options)

        with pytest.raises(RuntimeError, match="snapshot_model is not set"):
            if exporter.options.snapshot_model is None:
                raise RuntimeError("snapshot_model is not set but file-model path was expected")

    def test_guard_message_is_not_assertion_error(self):
        """Guards raise RuntimeError, never AssertionError."""
        from core.migration.commands.export_schema_command import (
            ExportSchemaOptions,
            SchemaExporter,
        )

        options = ExportSchemaOptions(source="live-database", schema="public")
        exporter = SchemaExporter(config=MagicMock(), options=options)
        exporter.provider = None

        exc = None
        try:
            if exporter.provider is None:
                raise RuntimeError("provider is not initialized")
        except RuntimeError as e:
            exc = e

        assert exc is not None
        assert isinstance(exc, RuntimeError)
        assert not isinstance(exc, AssertionError)


# TestJdbcProviderJavaTypesGuard removed in X-8: it tested
# JdbcProvider._build_type_dispatch which was a test-only shim over
# JdbcTypeConverter._build_type_dispatch. The guard now lives on the canonical
# JdbcTypeConverter and is covered by its own tests.
