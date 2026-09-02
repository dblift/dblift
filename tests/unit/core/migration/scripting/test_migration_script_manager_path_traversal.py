"""Unit tests for path traversal guard in MigrationScriptManager.get_all_scripts().

Security: verifies that files outside the configured migrations directory are rejected
even if they are discovered via a directory symlink that points outside the migrations dir.

The existing code already excludes file symlinks (is_symlink() check).
The missing guard is for files discovered via directory symlinks — those files are regular
files (is_symlink() == False), but their resolved path is outside the migrations directory.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dblift.core.logger import DbliftLogger, LogFormat
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager


class TestPathTraversalGuard:
    """Tests for the path traversal guard in get_all_scripts()."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        logger = DbliftLogger("test", LogFormat.TEXT)
        self.script_manager = MigrationScriptManager(logger)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_path_traversal_guard_allows_file_inside_migrations_dir(self):
        """Legitimate files inside the migrations directory must be loaded (AC #2, #3)."""
        migrations_dir = self.temp_dir / "migrations"
        migrations_dir.mkdir()

        (migrations_dir / "V1__create_table.sql").write_text("CREATE TABLE a (id INT);")
        (migrations_dir / "V2__add_column.sql").write_text("ALTER TABLE a ADD COLUMN name TEXT;")

        scripts = self.script_manager.get_all_scripts(migrations_dir, recursive=False)

        script_names = [Path(s).name for s in scripts]
        assert "V1__create_table.sql" in script_names, "V1 must be loaded"
        assert "V2__add_column.sql" in script_names, "V2 must be loaded"
        assert len(scripts) == 2

    def test_path_traversal_guard_rejects_file_outside_migrations_dir(self):
        """A file discovered via a directory symlink pointing outside the migrations dir must be ignored (AC #1, #3).

        Scenario: a directory symlink inside migrations/ points to an external directory.
        rglob() follows directory symlinks and finds regular files inside.
        Those files pass the is_symlink() == False filter but their resolved path
        is outside the migrations directory — the guard must reject them.
        """
        migrations_dir = self.temp_dir / "migrations"
        migrations_dir.mkdir()

        # Legitimate file inside the migrations directory
        legit_file = migrations_dir / "V1__create_table.sql"
        legit_file.write_text("CREATE TABLE foo (id INT);")

        # External directory with a migration file (outside the configured directory)
        outside_dir = self.temp_dir / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "V99__secret.sql"
        outside_file.write_text("DROP DATABASE prod;")

        # Create a directory symlink in migrations/ pointing to outside/
        # rglob() will follow this link and find V99__secret.sql as a regular file
        dir_symlink = migrations_dir / "linked_dir"
        try:
            dir_symlink.symlink_to(outside_dir)
        except (OSError, NotImplementedError):
            pytest.skip("Symbolic links are not supported on this platform")

        # Verify that rglob() follows the directory symlink (Python behavior)
        all_found = list(migrations_dir.rglob("*.sql"))
        dir_symlink_followed = any("V99__secret.sql" in str(p) for p in all_found)
        if not dir_symlink_followed:
            pytest.skip("This platform does not follow directory symlinks with rglob()")

        scripts = self.script_manager.get_all_scripts(migrations_dir, recursive=True)

        script_names = [Path(s).name for s in scripts]
        # The legitimate file must be present
        assert "V1__create_table.sql" in script_names, "The legitimate file must be loaded"
        # The file outside the directory (found via directory symlink) must NOT be loaded
        assert (
            "V99__secret.sql" not in script_names
        ), "File outside the directory (accessed via directory symlink) must not be loaded"

    def test_path_traversal_guard_rejects_outside_path_platform_independent(self):
        """Test the path traversal guard without relying on directory symlinks (platform-independent).

        Injects a file outside the migrations directory directly into glob results via a mock,
        simulating what would happen if rglob() followed a directory symlink to an external path.
        This test runs on all platforms (including macOS).

        Covers AC #1 and AC #3 in a platform-independent way.
        """
        migrations_dir = self.temp_dir / "migrations"
        migrations_dir.mkdir()

        # Legitimate file inside the migrations directory
        legit_file = migrations_dir / "V1__create_table.sql"
        legit_file.write_text("CREATE TABLE a (id INT);")

        # Real file outside the migrations directory (simulating access via directory symlink)
        outside_dir = self.temp_dir / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "V99__secret.sql"
        outside_file.write_text("DROP DATABASE prod;")

        # Patch Path.glob to inject the external file into discovery results,
        # simulating what rglob() would do on Linux when following a directory symlink.
        original_glob = Path.glob

        def patched_glob(path_self, pattern):
            results = list(original_glob(path_self, pattern))
            if path_self == migrations_dir:
                results.append(outside_file)
            return iter(results)

        with patch.object(Path, "glob", patched_glob):
            scripts = self.script_manager.get_all_scripts(migrations_dir, recursive=False)

        script_names = [Path(s).name for s in scripts]
        assert "V1__create_table.sql" in script_names, "The legitimate file must be loaded"
        assert (
            "V99__secret.sql" not in script_names
        ), "File outside the directory must be rejected by the path traversal guard"


class TestGetAllScriptsUnreadableDirectory:
    """Tests that an unreadable --scripts directory fails loudly instead of silently returning no results."""

    def setup_method(self):
        """Set up test fixtures."""
        self.unreadable_dir = tempfile.mkdtemp()
        with open(os.path.join(self.unreadable_dir, "V1__test.sql"), "w") as f:
            f.write("CREATE TABLE t(id INTEGER PRIMARY KEY);")
        os.chmod(self.unreadable_dir, 0o000)
        logger = DbliftLogger("test", LogFormat.TEXT)
        self.script_manager = MigrationScriptManager(logger)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        os.chmod(self.unreadable_dir, 0o755)
        shutil.rmtree(self.unreadable_dir, ignore_errors=True)

    @pytest.mark.skipif(
        os.name == "nt" or os.getuid() == 0,
        reason="permission bits aren't enforced for root or on Windows",
    )
    def test_unreadable_scripts_dir_raises_permission_error(self):
        with pytest.raises(PermissionError, match="Cannot read migrations directory"):
            self.script_manager.get_all_scripts(Path(self.unreadable_dir))
