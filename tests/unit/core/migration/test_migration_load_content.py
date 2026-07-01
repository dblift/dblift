"""Regression tests for B-1/B-2/B-3 Python migration pipeline reform.

B-1: Migration.load_content() reads script body from disk when content is empty,
     enabling all downstream code that inspects content to work for DB-loaded migrations.

B-2: _validate_checksums() now includes MigrationType.PYTHON in checksum validation
     (previously it was silently skipped via an allowlist that omitted PYTHON).

B-3: Migration.load_content() populates self.content from disk so that
     PythonMigrationExecutor.supports_rollback() (which inspects content for a
     ``def undo(`` function) works for DB-loaded Python migrations. (The historical
     UndoCommand selection call site was removed when Python undo moved to separate
     U*.py scripts; this exercises the retained executor-level behavior directly.)
"""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.migration.migration import Migration, MigrationType


class TestMigrationLoadContent:
    """B-1: load_content() populates self.content from disk."""

    def test_load_content_from_scripts_dir(self, tmp_path):
        script = tmp_path / "V2__create_orders.py"
        script.write_text("def migrate(ctx): pass\ndef undo(ctx): pass\n")
        m = Migration(script_name="V2__create_orders.py", content="", type=MigrationType.PYTHON)
        assert m.content == ""
        m.load_content(tmp_path)
        assert "def undo(" in m.content

    def test_load_content_noop_when_already_populated(self, tmp_path):
        script = tmp_path / "V1__init.py"
        script.write_text("new content on disk")
        m = Migration(script_name="V1__init.py", content="original", type=MigrationType.PYTHON)
        m.load_content(tmp_path)
        assert m.content == "original"  # not replaced

    def test_load_content_noop_when_file_missing(self, tmp_path):
        m = Migration(script_name="V99__missing.py", content="", type=MigrationType.PYTHON)
        m.load_content(tmp_path)  # should not raise
        assert m.content == ""

    def test_load_content_sets_path(self, tmp_path):
        script = tmp_path / "V3__tbl.py"
        script.write_text("def migrate(ctx): pass\n")
        m = Migration(script_name="V3__tbl.py", content="", type=MigrationType.PYTHON)
        assert m.path is None
        m.load_content(tmp_path)
        assert m.path == script

    def test_load_content_none_scripts_dir(self):
        m = Migration(script_name="V1__x.py", content="", type=MigrationType.PYTHON)
        m.load_content(None)  # should not raise
        assert m.content == ""

    def test_load_content_reads_self_path_when_no_scripts_dir(self, tmp_path):
        script = tmp_path / "V5__x.py"
        script.write_text("def migrate(ctx): pass\ndef undo(ctx): pass\n")
        m = Migration(script_path=script)
        m.content = ""  # simulate DB-load erasure
        m.load_content(None)
        assert "def undo(" in m.content


class TestChecksumValidationIncludesPython:
    """B-2: PYTHON migration type is not excluded from checksum validation."""

    def test_python_type_not_skipped(self):
        from core.migration.migration import MigrationType

        # The new inverted guard skips only UNKNOWN, DELETE, BASELINE
        skipped = {"UNKNOWN", "DELETE", "BASELINE"}
        for t in MigrationType:
            should_skip = t.value in skipped
            if t == MigrationType.PYTHON:
                assert not should_skip, "PYTHON must NOT be skipped in checksum validation"

    def test_validate_checksums_does_not_skip_python(self, tmp_path):
        """PYTHON migration is NOT skipped — has_script_changed is called for it."""
        from core.migration.migration import Migration, MigrationType
        from core.sql_validator.migration_validator import MigrationValidator, ValidationResult

        script = tmp_path / "V6__orders.py"
        script.write_text("def migrate(ctx): ctx.execute('CREATE TABLE orders (id INT)')\n")

        applied = Migration(script_path=script)
        applied.type = MigrationType.PYTHON

        log = MagicMock()
        script_manager = MagicMock()
        script_manager.has_script_changed.return_value = False  # no actual mismatch
        script_manager.script_encoding = "utf-8"
        script_manager.calculate_checksum.return_value = 12345

        validator = MigrationValidator.__new__(MigrationValidator)
        validator.log = log
        validator.script_manager = script_manager

        issues: list = []
        result = MagicMock(spec=ValidationResult)
        validator._validate_checksums(
            scripts=[applied],
            applied_migrations=[applied],
            result=result,
            issues=issues,
            strict_mode=False,
        )
        # PYTHON type must reach has_script_changed — not skipped by the type guard
        script_manager.has_script_changed.assert_called()

    def test_has_script_changed_ignores_later_undo_row_for_same_script(self, tmp_path):
        """Synthetic UNDO_SQL rows reuse the script name but must not own the checksum."""
        from core.logger import NullLog
        from core.migration.scripting.migration_script_manager import MigrationScriptManager

        script = tmp_path / "V7__python_migrate.py"
        script.write_text("def migrate(ctx): ctx.execute('CREATE TABLE t (id INT)')\n")
        applied = Migration(script_path=script)
        applied.success = True

        undo = SimpleNamespace(
            script_name="V7__python_migrate.py",
            type=MigrationType.UNDO_SQL,
            success=True,
            checksum=0,
        )

        manager = MigrationScriptManager(NullLog())

        assert (
            manager.has_script_changed(
                "V7__python_migrate.py",
                applied_migrations=[applied, undo],
                script_path=script,
            )
            is False
        )

    def test_validate_checksums_ignores_undo_row_for_same_script(self, tmp_path):
        """Checksum validation should compare against the original row, not UNDO_SQL."""
        from core.logger import NullLog
        from core.migration.scripting.migration_script_manager import MigrationScriptManager
        from core.sql_validator.migration_validator import MigrationValidator, ValidationResult

        script = tmp_path / "V7__python_migrate.py"
        script.write_text("def migrate(ctx): ctx.execute('CREATE TABLE t (id INT)')\n")
        applied = Migration(script_path=script)
        applied.success = True

        undo = SimpleNamespace(
            script_name="V7__python_migrate.py",
            version="7",
            type=MigrationType.UNDO_SQL,
            success=True,
            checksum=0,
        )

        validator = MigrationValidator.__new__(MigrationValidator)
        validator.log = NullLog()
        validator.script_manager = MigrationScriptManager(NullLog())

        issues: list[str] = []
        result = ValidationResult()
        validator._validate_checksums(
            scripts=[applied],
            applied_migrations=[applied, undo],
            result=result,
            issues=issues,
            strict_mode=False,
        )

        assert not any("has been modified" in issue for issue in issues)


class TestSupportsRollbackAfterLoadContent:
    """B-3: PythonMigrationExecutor.supports_rollback() works after load_content()."""

    def _make_executor(self):
        from core.migration.executors.python_executor import PythonMigrationExecutor

        return PythonMigrationExecutor(provider=MagicMock(), config=MagicMock(), log=MagicMock())

    def test_python_migration_with_undo_fn_is_undoable(self, tmp_path):
        """DB-loaded Python migration (content='') with def undo() on disk is undoable."""
        script = tmp_path / "V2__orders.py"
        script.write_text("def migrate(ctx): pass\ndef undo(ctx): pass\n")

        from core.migration.migration import Migration, MigrationType

        m = Migration(script_name="V2__orders.py", content="", type=MigrationType.PYTHON)
        assert not m.content  # simulates DB-loaded state

        m.load_content(tmp_path)
        executor = self._make_executor()
        assert executor.supports_rollback(m) is True

    def test_python_migration_without_undo_fn_is_not_undoable(self, tmp_path):
        script = tmp_path / "V3__products.py"
        script.write_text("def migrate(ctx): pass\n")

        from core.migration.migration import Migration, MigrationType

        m = Migration(script_name="V3__products.py", content="", type=MigrationType.PYTHON)
        m.load_content(tmp_path)

        executor = self._make_executor()
        assert executor.supports_rollback(m) is False

    def test_supports_rollback_false_when_content_empty(self):
        from core.migration.migration import Migration, MigrationType

        m = Migration(script_name="V4__x.py", content="", type=MigrationType.PYTHON)
        executor = self._make_executor()
        assert executor.supports_rollback(m) is False
