"""
Tests for migration format detection and routing.

These tests verify that DBLIFT can correctly detect migration formats
and route them to the appropriate executor.
"""

import logging
from pathlib import Path

import pytest

from core.migration.formats import MigrationFormat, MigrationFormatDetector
from core.migration.migration import Migration, MigrationType

pytestmark = [pytest.mark.unit]


class TestMigrationFormatEnum:
    """Tests for MigrationFormat enum."""

    def test_sql_format_properties(self):
        """Test SQL format properties."""
        assert MigrationFormat.SQL.value == "sql"
        assert str(MigrationFormat.SQL) == "sql"

    def test_python_format_properties(self):
        """Test Python format properties."""
        assert MigrationFormat.PYTHON.value == "python"
        assert str(MigrationFormat.PYTHON) == "python"

    def test_all_formats_have_values(self):
        """Test that all formats have non-empty values."""
        for format in MigrationFormat:
            if format != MigrationFormat.UNKNOWN:
                assert format.value != ""


class TestMigrationFormatDetector:
    """Tests for MigrationFormatDetector."""

    def test_detect_sql_from_path(self):
        """Test detecting SQL format from file path."""
        path = Path("V1_0_0__create_table.sql")
        format = MigrationFormatDetector.detect_from_path(path)
        assert format == MigrationFormat.SQL

    def test_detect_python_from_path(self):
        """Test detecting Python format from file path."""
        path = Path("V1_0_0__migration.py")
        format = MigrationFormatDetector.detect_from_path(path)
        assert format == MigrationFormat.PYTHON

    def test_detect_javascript_from_path(self):
        """Test detecting JavaScript format from file path."""
        path = Path("V1_0_0__migration.js")
        format = MigrationFormatDetector.detect_from_path(path)
        assert format == MigrationFormat.JAVASCRIPT

    def test_detect_cypher_from_path(self):
        """Test detecting Cypher format from file path."""
        path = Path("V1_0_0__migration.cypher")
        format = MigrationFormatDetector.detect_from_path(path)
        assert format == MigrationFormat.CYPHER

    def test_detect_unknown_format(self):
        """Test detecting unknown format."""
        path = Path("V1_0_0__migration.txt")
        format = MigrationFormatDetector.detect_from_path(path)
        assert format == MigrationFormat.UNKNOWN

    def test_detect_from_filename(self):
        """Test detecting format from filename string."""
        format = MigrationFormatDetector.detect_from_filename("test.sql")
        assert format == MigrationFormat.SQL

    def test_is_migration_file(self):
        """Test checking if a file is a migration file."""
        assert MigrationFormatDetector.is_migration_file(Path("test.sql")) is True
        assert MigrationFormatDetector.is_migration_file(Path("test.py")) is True
        assert MigrationFormatDetector.is_migration_file(Path("README.md")) is False
        assert MigrationFormatDetector.is_migration_file(Path("test.txt")) is False


class TestMigrationFormatInMigration:
    """Tests for migration format in Migration model."""

    def test_migration_detects_sql_format(self, tmp_path):
        """Test that Migration detects SQL format from file path."""
        # Create a temporary SQL file
        sql_file = tmp_path / "V1_0_0__test.sql"
        sql_file.write_text("CREATE TABLE test (id INT);")

        # Create migration from file
        migration = Migration(script_path=sql_file)

        # Verify format was detected
        assert hasattr(migration, "format")
        assert migration.format == MigrationFormat.SQL

    def test_migration_detects_python_format(self, tmp_path):
        """Test that Migration detects Python format from file path."""
        # Create a temporary Python file
        py_file = tmp_path / "V1_0_0__test.py"
        py_file.write_text("def upgrade():\n    pass")

        # Create migration from file
        migration = Migration(script_path=py_file)

        # Verify format was detected
        assert hasattr(migration, "format")
        assert migration.format == MigrationFormat.PYTHON

    def test_migration_defaults_to_sql_format(self):
        """Test that Migration defaults to SQL format when no path provided."""
        # Create migration without file path
        migration = Migration(script_name="V1_0_0__test.sql", content="CREATE TABLE test (id INT);")

        # Verify default format is SQL
        assert hasattr(migration, "format")
        assert migration.format == MigrationFormat.SQL

    def test_baseline_marker_name_does_not_warn(self, caplog):
        """BASELINE rows are synthetic markers (e.g. '<< Flyway Baseline >>'), not real
        files — format detection should not run against them and log a spurious warning."""
        with caplog.at_level(logging.WARNING):
            migration = Migration(
                script_name="<< Flyway Baseline >>",
                type=MigrationType.BASELINE,
                version=None,
            )

        assert not any("Unknown migration file extension" in r.message for r in caplog.records)
        assert migration.format == MigrationFormat.UNKNOWN


class TestMigrationExecutorArchitecture:
    """Tests to verify the executor architecture is ready for extension."""

    def test_executor_factory_exists(self):
        """Test that MigrationExecutorFactory exists and can be imported."""
        from core.migration.executors import MigrationExecutorFactory

        assert MigrationExecutorFactory is not None

    def test_base_executor_exists(self):
        """Test that BaseMigrationExecutor interface exists."""
        from core.migration.executors import BaseMigrationExecutor

        assert BaseMigrationExecutor is not None

    def test_sql_executor_exists(self):
        """Test that SqlMigrationExecutor exists."""
        from core.migration.executors import SqlMigrationExecutor

        assert SqlMigrationExecutor is not None

    def test_executor_factory_supports_sql(self):
        """Test that executor factory supports SQL format."""
        from unittest.mock import Mock

        from core.migration.executors import MigrationExecutorFactory

        # Create factory with mocks
        factory = MigrationExecutorFactory(
            provider=Mock(), config=Mock(database=Mock(type="postgresql")), log=Mock()
        )

        # Verify SQL is supported
        assert MigrationFormat.SQL in factory.get_supported_formats()

    def test_executor_factory_can_get_sql_executor(self):
        """Test that factory can provide SQL executor."""
        from unittest.mock import Mock

        from core.migration.executors import MigrationExecutorFactory

        # Create factory
        factory = MigrationExecutorFactory(
            provider=Mock(), config=Mock(database=Mock(type="postgresql")), log=Mock()
        )

        # Create a SQL migration
        migration = Migration(script_name="V1_0_0__test.sql", content="CREATE TABLE test (id INT);")

        # Get executor
        executor = factory.get_executor(migration)

        # Verify we got an executor
        assert executor is not None
        assert executor.can_execute(migration)

    def test_architecture_ready_for_new_formats(self):
        """Test that architecture is ready to accept new format executors."""
        from unittest.mock import Mock

        from core.migration.executors import BaseMigrationExecutor, MigrationExecutorFactory

        # Create a mock executor class for testing
        class MockPythonExecutor(BaseMigrationExecutor):
            def can_execute(self, migration):
                return migration.format == MigrationFormat.PYTHON

            def execute_migration(self, migration, dry_run=False, **kwargs):
                from core.migration.executors import MigrationExecutionResult

                return MigrationExecutionResult(
                    success=True, migration=migration, execution_time_ms=0
                )

            def validate_migration(self, migration):
                return True, []

            def get_supported_formats(self):
                return [MigrationFormat.PYTHON]

        # Create factory
        factory = MigrationExecutorFactory(
            provider=Mock(), config=Mock(database=Mock(type="postgresql")), log=Mock()
        )

        # Register new executor
        factory.register_executor_class(MigrationFormat.PYTHON, MockPythonExecutor)

        # Verify it's registered
        assert MigrationFormat.PYTHON in factory.get_supported_formats()

        # Create a Python migration (without file, just for testing)
        migration = Migration(script_name="V1_0_0__test.py", content="def upgrade():\n    pass")
        migration.format = MigrationFormat.PYTHON

        # Verify factory can route to it
        executor = factory.get_executor(migration)
        assert executor is not None
        assert isinstance(executor, MockPythonExecutor)


class TestMigrationDetermineType:
    """Tests for Migration._determine_type() — callback detection."""

    def test_aftereach_is_callback(self):
        m = Migration(script_name="afterEach__cleanup.sql")
        assert m.type == MigrationType.CALLBACK

    def test_beforeeach_is_callback(self):
        m = Migration(script_name="beforeEach__setup.sql")
        assert m.type == MigrationType.CALLBACK

    def test_aftermigrateerror_is_callback(self):
        """Cas manquant avant le fix — afterMigrateError n'était pas détecté."""
        m = Migration(script_name="afterMigrateError__cleanup.sql")
        assert m.type == MigrationType.CALLBACK

    def test_aftermigrate_is_callback(self):
        m = Migration(script_name="afterMigrate__log.sql")
        assert m.type == MigrationType.CALLBACK

    def test_beforemigrate_is_callback(self):
        m = Migration(script_name="beforeMigrate__check.sql")
        assert m.type == MigrationType.CALLBACK

    def test_versioned_is_not_callback(self):
        m = Migration(script_name="V1_0_0__create_table.sql")
        assert m.type == MigrationType.SQL

    def test_empty_script_name_is_unknown(self):
        """_determine_type() returns UNKNOWN for empty script_name."""
        m = Migration(script_name="dummy.sql")
        m.script_name = ""
        assert m._determine_type() == MigrationType.UNKNOWN

    def test_none_script_name_is_unknown(self):
        """_determine_type() returns UNKNOWN for None script_name."""
        m = Migration(script_name="dummy.sql")
        m.script_name = None
        assert m._determine_type() == MigrationType.UNKNOWN

    def test_case_insensitive_detection(self):
        """Callback detection est insensible à la casse."""
        m = Migration(script_name="AFTEREACH__test.sql")
        assert m.type == MigrationType.CALLBACK

    def test_case_insensitive_new_events(self):
        """Case-insensitivity fonctionne aussi pour les events ajoutés par la story 10-15."""
        m = Migration(script_name="AFTERMIGRATEERROR__test.sql")
        assert m.type == MigrationType.CALLBACK

    def test_beforeversioned_is_callback(self):
        """beforeVersioned était dans la liste originale (renommé de 'beforeversioned')."""
        m = Migration(script_name="beforeVersioned__check.sql")
        assert m.type == MigrationType.CALLBACK

    def test_afterrepeatable_is_callback(self):
        """afterRepeatable était dans la liste originale (renommé de 'afterrepeatable')."""
        m = Migration(script_name="afterRepeatable__cleanup.sql")
        assert m.type == MigrationType.CALLBACK

    def test_callback_prefixes_constant_covers_supported_events(self):
        """_CALLBACK_PREFIXES lists only callback events dispatched by commands."""
        from core.migration.migration import _CALLBACK_PREFIXES

        assert len(_CALLBACK_PREFIXES) == 19
        assert "beforeEachMigrate" in _CALLBACK_PREFIXES
        assert "afterEachMigrate" in _CALLBACK_PREFIXES
        assert "beforeEachValidate" not in _CALLBACK_PREFIXES
        assert "afterEachValidate" not in _CALLBACK_PREFIXES
        assert "beforeEachClean" not in _CALLBACK_PREFIXES
        assert "afterEachClean" not in _CALLBACK_PREFIXES

    def test_callback_prefixes_in_sync_with_script_manager(self):
        """Chaque prefix de _CALLBACK_PREFIXES doit être reconnu comme CALLBACK
        par MigrationScriptManager.parse_filename (validation fonctionnelle de sync)."""
        from unittest.mock import MagicMock

        from core.migration.migration import _CALLBACK_PREFIXES, MigrationType
        from core.migration.scripting.migration_script_manager import MigrationScriptManager

        sm = MigrationScriptManager(MagicMock())
        for prefix in _CALLBACK_PREFIXES:
            filename = f"{prefix}__sync_check.sql"
            mtype, version, description, tags = sm.parse_filename(filename)
            assert mtype == MigrationType.CALLBACK, (
                f"Le prefix '{prefix}' est dans _CALLBACK_PREFIXES mais "
                f"MigrationScriptManager.parse_filename retourne {mtype} pour '{filename}'"
            )

    # --- Story 12-6: Flyway naming convention strict checks ---

    # True positives (AC#1-4)
    def test_v_followed_by_digit_is_versioned(self):
        assert Migration(script_name="V1__create.sql").type == MigrationType.SQL

    def test_v_dotted_version_is_versioned(self):
        assert Migration(script_name="V1.0__create.sql").type == MigrationType.SQL

    def test_r_double_underscore_is_repeatable(self):
        assert Migration(script_name="R__setup.sql").type == MigrationType.REPEATABLE

    def test_u_followed_by_digit_is_undo(self):
        assert Migration(script_name="U1__rollback.sql").type == MigrationType.UNDO_SQL

    def test_b_followed_by_digit_is_baseline(self):
        assert Migration(script_name="B1__baseline.sql").type == MigrationType.BASELINE

    # False positives — must return UNKNOWN (AC#1-4)
    def test_validate_sql_is_unknown(self):
        assert Migration(script_name="validate.sql").type == MigrationType.UNKNOWN

    def test_repair_sql_is_unknown(self):
        assert Migration(script_name="repair.sql").type == MigrationType.UNKNOWN

    def test_undo_sql_without_version_is_unknown(self):
        assert Migration(script_name="undo.sql").type == MigrationType.UNKNOWN

    def test_backup_sql_is_unknown(self):
        assert Migration(script_name="backup.sql").type == MigrationType.UNKNOWN

    # Edge cases (AC#2, AC#5)
    def test_v_without_version_number_is_unknown(self):
        """V__ sans numéro de version → UNKNOWN (pas convention Flyway)."""
        assert Migration(script_name="V__nodescription.sql").type == MigrationType.UNKNOWN

    def test_r_lowercase_double_underscore_is_repeatable(self):
        """r__ en minuscule → REPEATABLE (case-insensitive via .lower())."""
        assert Migration(script_name="r__lowercase.sql").type == MigrationType.REPEATABLE

    def test_views_setup_sql_is_unknown(self):
        """views_setup.sql commence par 'v' mais n'est pas Flyway → UNKNOWN."""
        assert Migration(script_name="views_setup.sql").type == MigrationType.UNKNOWN

    def test_reset_sql_is_unknown(self):
        """reset.sql commence par 'r' mais pas r__ → UNKNOWN."""
        assert Migration(script_name="reset.sql").type == MigrationType.UNKNOWN

    def test_update_sql_is_unknown(self):
        """update.sql commence par 'u' mais pas u<digit> → UNKNOWN."""
        assert Migration(script_name="update.sql").type == MigrationType.UNKNOWN

    def test_va_alpha_version_is_unknown(self):
        """Va__create.sql : V + lettre (pas chiffre) → UNKNOWN.

        _determine_type() utilise intentionnellement ^v\\d (digit-only) plutôt que
        ^v[a-z0-9] pour éviter de classer 'validate.sql' comme SQL.
        parse_filename() accepte les versions alphabétiques (ex: VA__), mais
        _determine_type() est un pré-filtre strict — la validation complète est
        déléguée à MigrationScriptManager (cohérence AC#5 limitée au cas digit).
        """
        assert Migration(script_name="Va__create.sql").type == MigrationType.UNKNOWN

    def test_r_with_version_number_is_unknown(self):
        """R1__setup.sql : 'R' + version → UNKNOWN (Flyway repeatable n'a pas de version).

        Le pattern repeatable Flyway est R__<desc> sans numéro de version.
        'R1__setup.sql' ne commence pas par 'r__' → UNKNOWN.
        """
        assert Migration(script_name="R1__setup.sql").type == MigrationType.UNKNOWN


class TestMigrationTypeSqlRename:
    """Structural tests for MigrationType.VERSIONED → MigrationType.SQL rename (story 17-4)."""

    def test_migration_type_sql_exists(self):
        """AC#7.4: MigrationType.SQL exists and has value 'SQL'."""
        assert hasattr(MigrationType, "SQL")
        assert MigrationType.SQL.value == "SQL"

    def test_migration_type_versioned_gone(self):
        """AC#7.3: MigrationType.VERSIONED no longer exists."""
        assert not hasattr(MigrationType, "VERSIONED")

    def test_other_enum_members_unchanged(self):
        """AC#1.3: Other enum members remain unchanged."""
        assert MigrationType.REPEATABLE.value == "REPEATABLE"
        assert MigrationType.UNDO_SQL.value == "UNDO_SQL"
        assert MigrationType.BASELINE.value == "BASELINE"
        assert MigrationType.CALLBACK.value == "CALLBACK"
        assert MigrationType.DELETE.value == "DELETE"
        assert MigrationType.UNKNOWN.value == "UNKNOWN"

    def test_determine_type_returns_sql(self):
        """AC#2.1: V1__init.sql → MigrationType.SQL."""
        m = Migration(script_name="V1__init.sql")
        assert m.type == MigrationType.SQL
