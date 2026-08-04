"""Unit tests for MigrationScriptManager per-directory recursive functionality."""

import tempfile
from pathlib import Path

import pytest

from config.dblift_config import MigrationsConfig
from core.logger import DbliftLogger, LogFormat
from core.migration.scripting.migration_script_manager import MigrationScriptManager

pytestmark = [pytest.mark.unit]


class TestMigrationScriptManagerPerDirectoryRecursive:
    """Test per-directory recursive settings in MigrationScriptManager."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.primary_dir = self.temp_dir / "primary"
        self.additional_dir1 = self.temp_dir / "additional1"
        self.additional_dir2 = self.temp_dir / "additional2"

        # Create directories
        self.primary_dir.mkdir()
        self.additional_dir1.mkdir()
        self.additional_dir2.mkdir()

        # Create subdirectories
        (self.primary_dir / "subdir").mkdir()
        (self.additional_dir1 / "subdir").mkdir()
        (self.additional_dir2 / "subdir").mkdir()

        # Create logger
        logger = DbliftLogger("test", LogFormat.TEXT)
        self.script_manager = MigrationScriptManager(logger)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_get_all_scripts_with_per_directory_recursive(self):
        """Test get_all_scripts with per-directory recursive settings."""
        # Create files in primary directory and subdirectory
        (self.primary_dir / "V1_0_0__primary.sql").write_text("CREATE TABLE primary;")
        (self.primary_dir / "subdir" / "V1_0_1__primary_sub.sql").write_text(
            "CREATE TABLE primary_sub;"
        )

        # Create files in additional directories
        (self.additional_dir1 / "V1_0_2__add1.sql").write_text("CREATE TABLE add1;")
        (self.additional_dir1 / "subdir" / "V1_0_3__add1_sub.sql").write_text(
            "CREATE TABLE add1_sub;"
        )

        (self.additional_dir2 / "V1_0_4__add2.sql").write_text("CREATE TABLE add2;")
        (self.additional_dir2 / "subdir" / "V1_0_5__add2_sub.sql").write_text(
            "CREATE TABLE add2_sub;"
        )

        # Test with recursive=True for all (default)
        scripts = self.script_manager.get_all_scripts(
            self.primary_dir,
            recursive=True,
            additional_dirs=[self.additional_dir1, self.additional_dir2],
        )
        assert len(scripts) == 6  # All files including subdirectories

        # Test with recursive=False for all
        scripts = self.script_manager.get_all_scripts(
            self.primary_dir,
            recursive=False,
            additional_dirs=[self.additional_dir1, self.additional_dir2],
        )
        assert len(scripts) == 3  # Only top-level files

        # Test with per-directory recursive settings
        dir_recursive_map = {
            self.primary_dir: True,  # Recursive
            self.additional_dir1: False,  # Not recursive
            self.additional_dir2: True,  # Recursive
        }
        scripts = self.script_manager.get_all_scripts(
            self.primary_dir,
            recursive=True,  # Default for directories not in map
            additional_dirs=[self.additional_dir1, self.additional_dir2],
            dir_recursive_map=dir_recursive_map,
        )
        # Should get: primary (2 files), add1 (1 file, no subdir), add2 (2 files)
        assert len(scripts) == 5
        script_names = [Path(s).name if "/" not in s else s.split("/")[-1] for s in scripts]
        assert "V1_0_0__primary.sql" in script_names
        assert "V1_0_1__primary_sub.sql" in script_names
        assert "V1_0_2__add1.sql" in script_names
        assert "V1_0_3__add1_sub.sql" not in script_names  # Should be excluded
        assert "V1_0_4__add2.sql" in script_names
        assert "V1_0_5__add2_sub.sql" in script_names

    def test_load_migration_scripts_with_per_directory_recursive(self):
        """Test load_migration_scripts with per-directory recursive settings."""
        # Create migration files
        (self.primary_dir / "V1_0_0__primary.sql").write_text("CREATE TABLE primary;")
        (self.primary_dir / "subdir" / "V1_0_1__primary_sub.sql").write_text(
            "CREATE TABLE primary_sub;"
        )
        (self.additional_dir1 / "V1_0_2__add1.sql").write_text("CREATE TABLE add1;")
        (self.additional_dir1 / "subdir" / "V1_0_3__add1_sub.sql").write_text(
            "CREATE TABLE add1_sub;"
        )

        # Test with per-directory recursive settings
        dir_recursive_map = {
            self.primary_dir: True,
            self.additional_dir1: False,
        }
        migrations = self.script_manager.load_migration_scripts(
            self.primary_dir,
            recursive=True,
            additional_dirs=[self.additional_dir1],
            dir_recursive_map=dir_recursive_map,
        )

        # Should find migrations from primary (recursive) and add1 (non-recursive)
        all_migrations = []
        for migration_list in migrations.values():
            all_migrations.extend(migration_list)

        assert len(all_migrations) == 3  # V1_0_0, V1_0_1, V1_0_2 (but not V1_0_3)
        script_names = [m.script_name for m in all_migrations]
        assert any("V1_0_0__primary.sql" in name for name in script_names)
        assert any("V1_0_1__primary_sub.sql" in name for name in script_names)
        assert any("V1_0_2__add1.sql" in name for name in script_names)
        assert not any("V1_0_3__add1_sub.sql" in name for name in script_names)

    def test_load_migration_scripts_script_name_matches_primary_dir_convention(self):
        """A migration from an additional directory must get the same bare
        filename as script_name that a migration from the primary directory
        gets — not a directory-qualified (and on Unix absolute) path.

        script_name is what gets persisted into the schema history "script"
        column, so a directory-qualified value there makes history rows
        dependent on the absolute path the migrations directory happened to
        be mounted at, breaking validate/repair after a move.
        """
        (self.primary_dir / "V1_0_0__primary.sql").write_text("CREATE TABLE primary;")
        (self.additional_dir1 / "V1_0_2__add1.sql").write_text("CREATE TABLE add1;")

        migrations = self.script_manager.load_migration_scripts(
            self.primary_dir,
            recursive=False,
            additional_dirs=[self.additional_dir1],
        )

        all_migrations = [m for migration_list in migrations.values() for m in migration_list]
        by_name = {m.script_name: m for m in all_migrations}

        assert "V1_0_0__primary.sql" in by_name
        assert "V1_0_2__add1.sql" in by_name, (
            "script_name for a migration from an additional directory should be the "
            f"bare filename, matching the primary directory convention; got "
            f"{[m.script_name for m in all_migrations]}"
        )

    def test_load_migration_scripts_finds_subdirectory_file_in_second_additional_dir(self):
        """A migration nested in a subdirectory of an additional directory that is
        not the first one passed via additional_dirs must still be discovered and
        actually readable — not just found by get_all_scripts and then dropped
        when load_migration_scripts reconstructs its path for reading.
        """
        (self.primary_dir / "V1_0_0__primary.sql").write_text("CREATE TABLE primary;")
        (self.additional_dir1 / "V1_0_1__add1.sql").write_text("CREATE TABLE add1;")
        (self.additional_dir2 / "subdir" / "V1_0_2__add2_sub.sql").write_text(
            "CREATE TABLE add2_sub;"
        )

        migrations = self.script_manager.load_migration_scripts(
            self.primary_dir,
            recursive=True,
            additional_dirs=[self.additional_dir1, self.additional_dir2],
        )

        all_migrations = [m for migration_list in migrations.values() for m in migration_list]
        script_names = [m.script_name for m in all_migrations]

        assert "V1_0_0__primary.sql" in script_names
        assert "V1_0_1__add1.sql" in script_names
        assert "V1_0_2__add2_sub.sql" in script_names, (
            "migration nested in a subdirectory of the second additional directory "
            f"was not loaded; got {script_names}"
        )

    def test_load_migration_scripts_single_directory_with_subdirectory(self):
        """Regression guard: a single scripts directory (no additional_dirs) with
        a migration nested in a subdirectory must still be loaded correctly.
        """
        (self.primary_dir / "V1_0_0__primary.sql").write_text("CREATE TABLE primary;")
        (self.primary_dir / "subdir" / "V1_0_1__primary_sub.sql").write_text(
            "CREATE TABLE primary_sub;"
        )

        migrations = self.script_manager.load_migration_scripts(
            self.primary_dir,
            recursive=True,
        )

        all_migrations = [m for migration_list in migrations.values() for m in migration_list]
        script_names = [m.script_name for m in all_migrations]

        assert "V1_0_0__primary.sql" in script_names
        assert "V1_0_1__primary_sub.sql" in script_names

    def test_load_migration_scripts_multiple_directories_flat_files_only(self):
        """Regression guard: multiple scripts directories with only flat (non-nested)
        files in each must all be loaded correctly.
        """
        (self.primary_dir / "V1_0_0__primary.sql").write_text("CREATE TABLE primary;")
        (self.additional_dir1 / "V1_0_1__add1.sql").write_text("CREATE TABLE add1;")
        (self.additional_dir2 / "V1_0_2__add2.sql").write_text("CREATE TABLE add2;")

        migrations = self.script_manager.load_migration_scripts(
            self.primary_dir,
            recursive=True,
            additional_dirs=[self.additional_dir1, self.additional_dir2],
        )

        all_migrations = [m for migration_list in migrations.values() for m in migration_list]
        script_names = [m.script_name for m in all_migrations]

        assert "V1_0_0__primary.sql" in script_names
        assert "V1_0_1__add1.sql" in script_names
        assert "V1_0_2__add2.sql" in script_names

    def test_get_callbacks_by_event_with_per_directory_recursive(self):
        """Test get_callbacks_by_event with per-directory recursive settings."""
        # Create callback files
        (self.primary_dir / "beforeMigrate__callback.sql").write_text("SELECT 1;")
        (self.primary_dir / "subdir" / "beforeMigrate__callback_sub.sql").write_text("SELECT 2;")
        (self.additional_dir1 / "beforeMigrate__callback_add1.sql").write_text("SELECT 3;")
        (self.additional_dir1 / "subdir" / "beforeMigrate__callback_add1_sub.sql").write_text(
            "SELECT 4;"
        )

        # Test with per-directory recursive settings
        dir_recursive_map = {
            self.primary_dir: True,
            self.additional_dir1: False,
        }
        callbacks = self.script_manager.get_callbacks_by_event(
            self.primary_dir,
            "beforeMigrate",
            recursive=True,
            additional_dirs=[self.additional_dir1],
            dir_recursive_map=dir_recursive_map,
        )

        # Should find callbacks from primary (recursive) and add1 (non-recursive)
        assert len(callbacks) == 3  # 2 from primary, 1 from add1
        script_names = [cb.script_name for cb in callbacks]
        assert any("beforeMigrate__callback.sql" in name for name in script_names)
        assert any("beforeMigrate__callback_sub.sql" in name for name in script_names)
        assert any("beforeMigrate__callback_add1.sql" in name for name in script_names)
        assert not any("beforeMigrate__callback_add1_sub.sql" in name for name in script_names)


class TestObjectFormDirectoryConfigDiscovery:
    """Issue #818: object-form `directories:` entries must resolve to the
    directory the user configured, so file discovery finds their scripts.

    Pins the full pipeline: MigrationsConfig.get_directory_configs() ->
    MigrationScriptManager.get_all_scripts().
    """

    def setup_method(self):
        """Set up a real temp directory with a single top-level migration script."""
        self.temp_dir = Path(tempfile.mkdtemp())
        (self.temp_dir / "V1__init.sql").write_text("CREATE TABLE foo (id INT);")

        logger = DbliftLogger("test", LogFormat.TEXT)
        self.script_manager = MigrationScriptManager(logger)

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_object_form_entry_discovers_top_level_file(self):
        """Object-form entry (dict with 'directory' + 'recursive') must resolve
        to the configured directory and find the top-level script in it."""
        migrations_config = MigrationsConfig(
            directories=[{"directory": str(self.temp_dir), "recursive": True}],
        )
        dir_configs = migrations_config.get_directory_configs()

        assert dir_configs[0].path == str(self.temp_dir)

        scripts = self.script_manager.get_all_scripts(
            Path(dir_configs[0].path), recursive=dir_configs[0].recursive
        )
        assert scripts == ["V1__init.sql"]

    def test_string_form_entry_discovers_top_level_file(self):
        """Regression: the equivalent plain-string form must keep working."""
        migrations_config = MigrationsConfig(directories=[str(self.temp_dir)])
        dir_configs = migrations_config.get_directory_configs()

        assert dir_configs[0].path == str(self.temp_dir)

        scripts = self.script_manager.get_all_scripts(
            Path(dir_configs[0].path), recursive=dir_configs[0].recursive
        )
        assert scripts == ["V1__init.sql"]
