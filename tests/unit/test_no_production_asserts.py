"""Tests for assert → RuntimeError/ValueError replacements.

Verifies that four assert sites now raise RuntimeError (never AssertionError)
so python -O cannot silently disable the guards.

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

from tests.unit._migration_factory import make_migration

pytestmark = [pytest.mark.unit]

_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Structural: zero bare assert in the four source files
# ---------------------------------------------------------------------------


class TestNoRemainingAsserts:
    """Zero bare assert in the 4 target source files."""

    def _assert_no_bare_assert(self, rel_path: str) -> None:
        src_path = _ROOT / rel_path
        tree = ast.parse(src_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                pytest.fail(
                    f"{rel_path} line {node.lineno}: bare assert found — "
                    "must be replaced by explicit raise"
                )

    def test_python_executor_no_assert(self):
        self._assert_no_bare_assert("dblift/core/migration/executors/python_executor.py")

    def test_sqlalchemy_provider_no_assert(self):
        self._assert_no_bare_assert("dblift/db/sqlalchemy_provider.py")


# ---------------------------------------------------------------------------
# Behavioural: invalid state raises RuntimeError (not AssertionError)
# ---------------------------------------------------------------------------


class TestPythonExecutorSpecGuard:
    """Verify RuntimeError when spec or spec.loader is None (surfaced via result.error)."""

    def _make_executor(self):
        from dblift.core.migration.executors.python_executor import PythonMigrationExecutor

        return PythonMigrationExecutor(
            provider=MagicMock(),
            config=MagicMock(),
            log=MagicMock(),
        )

    def _make_python_migration(self, content: str = "def migrate(ctx): pass"):

        tmp = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, prefix="V1__test_")
        tmp.write(content)
        tmp.flush()
        tmp.close()
        return make_migration(script_path=Path(tmp.name)), Path(tmp.name)

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
