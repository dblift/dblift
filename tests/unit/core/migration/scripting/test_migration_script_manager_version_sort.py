"""Tests for semantic version sorting in MigrationScriptManager (Story 12-12)."""

import shutil
import tempfile
from pathlib import Path

import pytest

from dblift.core.logger import DbliftLogger, LogFormat
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager


class TestMigrationVersionSort:
    """Tests for semantic version sorting (BUG-07 fix)."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        logger = DbliftLogger("test", LogFormat.TEXT)
        self.mgr = MigrationScriptManager(logger)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir)

    def _create_scripts(self, filenames):
        """Create dummy migration files in temp_dir."""
        for name in filenames:
            (self.temp_dir / name).write_text("SELECT 1;")

    # --- AC#4: tri numérique simple (V1, V2, V9, V10, V11) ---

    def test_load_migration_scripts_numeric_order(self):
        """AC#4: V1, V2, V9, V10, V11 sorted numerically, not lexicographically."""
        self._create_scripts(["V1__a.sql", "V2__b.sql", "V9__c.sql", "V10__d.sql", "V11__e.sql"])
        result = self.mgr.load_migration_scripts(self.temp_dir)
        versions = [m.version for m in result[MigrationType.SQL]]
        assert versions == ["1", "2", "9", "10", "11"]

    def test_get_migration_scripts_numeric_order(self):
        """AC#4: get_migration_scripts also returns numeric order."""
        self._create_scripts(["V1__a.sql", "V2__b.sql", "V9__c.sql", "V10__d.sql", "V11__e.sql"])
        result = self.mgr.get_migration_scripts(self.temp_dir)
        versioned = [m for m in result if m.type == MigrationType.SQL]
        versions = [m.version for m in versioned]
        assert versions == ["1", "2", "9", "10", "11"]

    def test_load_migration_scripts_sort_independent_of_creation_order(self):
        """AC#4: Sort is correct regardless of file creation order (filesystem order not guaranteed)."""
        self._create_scripts(["V11__e.sql", "V10__d.sql", "V9__c.sql", "V2__b.sql", "V1__a.sql"])
        result = self.mgr.load_migration_scripts(self.temp_dir)
        versions = [m.version for m in result[MigrationType.SQL]]
        assert versions == ["1", "2", "9", "10", "11"]

    def test_load_migration_scripts_alphanumeric_numeric_prefix_order(self):
        """V8b sorts after V8 but before V9/V17, not lexicographically after V17."""
        self._create_scripts(["V17__later.sql", "V8b__synonym.sql", "V9__next.sql", "V8__base.sql"])
        result = self.mgr.load_migration_scripts(self.temp_dir)
        versions = [m.version for m in result[MigrationType.SQL]]
        assert versions == ["8", "8b", "9", "17"]

    # --- AC#5: tri sémantique multi-parties ---

    def test_multipart_version_sort_two_parts(self):
        """AC#5: V1.9 sorts before V1.10 (not lexicographic where '9' > '1')."""
        self._create_scripts(["V1.10__a.sql", "V1.9__b.sql"])
        result = self.mgr.load_migration_scripts(self.temp_dir)
        versions = [m.version for m in result[MigrationType.SQL]]
        assert versions == ["1.9", "1.10"]

    def test_multipart_version_sort_three_parts(self):
        """AC#5: V2.0.0 sorts before V10.0.0."""
        self._create_scripts(["V10.0.0__a.sql", "V2.0.0__b.sql"])
        result = self.mgr.load_migration_scripts(self.temp_dir)
        versions = [m.version for m in result[MigrationType.SQL]]
        assert versions == ["2.0.0", "10.0.0"]

    def test_multipart_version_sort_mixed(self):
        """AC#5: Mixed multi-part versions in correct semantic order."""
        self._create_scripts(
            [
                "V1.0__first.sql",
                "V1.9__second.sql",
                "V1.10__third.sql",
                "V2.0.0__fourth.sql",
                "V10.0.0__fifth.sql",
            ]
        )
        result = self.mgr.load_migration_scripts(self.temp_dir)
        versions = [m.version for m in result[MigrationType.SQL]]
        assert versions == ["1.0", "1.9", "1.10", "2.0.0", "10.0.0"]

    def test_get_migration_scripts_multipart_order(self):
        """AC#5: get_migration_scripts also respects multi-part semantic order."""
        self._create_scripts(["V1.10__a.sql", "V1.9__b.sql", "V2.0.0__c.sql", "V10.0.0__d.sql"])
        result = self.mgr.get_migration_scripts(self.temp_dir)
        versioned = [m for m in result if m.type == MigrationType.SQL]
        versions = [m.version for m in versioned]
        assert versions == ["1.9", "1.10", "2.0.0", "10.0.0"]

    def test_repeatable_migrations_are_sorted_deterministically(self):
        """Repeatables run after versioned scripts in deterministic filename order."""
        self._create_scripts(["R__zeta.sql", "R__alpha.sql", "R__Middle.sql", "V1__base.sql"])

        result = self.mgr.get_migration_scripts(self.temp_dir)
        repeatables = [m.script_name for m in result if m.type == MigrationType.REPEATABLE]

        assert repeatables == ["R__alpha.sql", "R__Middle.sql", "R__zeta.sql"]

    def test_sort_tolerates_none_version_from_malformed_file(self):
        """M3: Malformed V__.sql produces version=None; sort must not raise and None sorts first."""
        self._create_scripts(["V__.sql", "V2__b.sql", "V1__a.sql"])
        result = self.mgr.load_migration_scripts(self.temp_dir)
        versions = [m.version for m in result[MigrationType.SQL]]
        # None version sorts before numeric versions (None → "" < "1")
        assert versions[0] is None
        assert versions[1:] == ["1", "2"]


class TestParseFilenameAlphabeticVersion:
    """Tests for deterministic alphabetic version handling (BUG-11 fix)."""

    def setup_method(self):
        logger = DbliftLogger("test", LogFormat.TEXT)
        self.mgr = MigrationScriptManager(logger)

    # --- AC#6: versions alphabétiques déterministes ---

    def test_parse_filename_rejects_purely_alphabetic_version(self):
        """A version must start with a digit, so 'VA__desc.sql' is not a migration.

        Accepting it would also make ``Users__seed.sql`` a migration at version
        'sers' — the two have the same shape. See
        tests/unit/core/migration/test_version_naming_convention.py.
        """
        mtype, version, _, _ = self.mgr.parse_filename("VA__desc.sql")
        assert mtype == MigrationType.UNKNOWN
        assert version is None

    def test_parse_filename_alphanumeric_version_kept_verbatim(self):
        """AC#6: a mixed version is returned as written, never hashed."""
        mtype, version, desc, _ = self.mgr.parse_filename("V3.2A__desc.sql")
        assert mtype == MigrationType.SQL
        assert version == "3.2A"
        assert desc == "desc"

    def test_compare_versions_alpha_order(self):
        """AC#6: compare_versions('A', 'B') returns -1 (alphabetic order)."""
        result = self.mgr.compare_versions("A", "B")
        assert result == -1

    def test_compare_versions_alpha_equal(self):
        """compare_versions('A', 'A') returns 0."""
        result = self.mgr.compare_versions("A", "A")
        assert result == 0

    def test_compare_versions_alpha_reverse(self):
        """compare_versions('B', 'A') returns 1."""
        result = self.mgr.compare_versions("B", "A")
        assert result == 1

    def test_parse_filename_undo_alphanumeric_version(self):
        """Undo migrations also return the raw version string (no hash)."""
        mtype, version, _, _ = self.mgr.parse_filename("U3.2A__rollback.sql")
        assert mtype == MigrationType.UNDO_SQL
        assert version == "3.2A"

    def test_parse_filename_rejects_undo_with_purely_alphabetic_version(self):
        mtype, version, _, _ = self.mgr.parse_filename("UA__rollback.sql")
        assert mtype == MigrationType.UNKNOWN
        assert version is None

    def test_alpha_version_deterministic_across_calls(self):
        """Version string is stable across multiple parse calls (no hash randomness)."""
        results = [self.mgr.parse_filename("V3.2A__desc.sql")[1] for _ in range(10)]
        assert all(v == "3.2A" for v in results)

    # --- Edge cases: None versions and mixed alpha/numeric comparison ---

    def test_compare_versions_none_none(self):
        """compare_versions(None, None) returns 0 — both treated as empty string."""
        result = self.mgr.compare_versions(None, None)
        assert result == 0

    def test_compare_versions_none_before_numeric(self):
        """compare_versions(None, '1') returns -1 — None (empty) sorts before numeric version."""
        result = self.mgr.compare_versions(None, "1")
        assert result == -1

    def test_compare_versions_numeric_after_none(self):
        """compare_versions('1', None) returns 1 — numeric sorts after None."""
        result = self.mgr.compare_versions("1", None)
        assert result == 1

    def test_compare_versions_alpha_after_numeric(self):
        """Alpha version ('A') sorts after numeric version ('10') — string comparison."""
        result = self.mgr.compare_versions("A", "10")
        assert result == 1

    def test_compare_versions_numeric_before_alpha(self):
        """Numeric version ('10') sorts before alpha version ('A')."""
        result = self.mgr.compare_versions("10", "A")
        assert result == -1

    def test_compare_versions_alphanumeric_against_target_versions(self):
        assert self.mgr.compare_versions("8b", "17") == -1
        assert self.mgr.compare_versions("8b", "12") == -1
        assert self.mgr.compare_versions("8b", "9") == -1
        assert self.mgr.compare_versions("8b", "8") == 1


class TestIsVersionedScriptName:
    """is_versioned_script_name uses parse_filename (not Migration._determine_type)."""

    def setup_method(self):
        logger = DbliftLogger("test", LogFormat.TEXT)
        self.mgr = MigrationScriptManager(logger)

    def test_sql_and_py_versioned(self):
        assert self.mgr.is_versioned_script_name("V1_0_0__seed.sql") is True
        assert self.mgr.is_versioned_script_name("V1_0_0__seed.py") is True

    def test_letter_version_rejected(self):
        """A version must start with a digit — both classifiers agree on this."""
        assert self.mgr.is_versioned_script_name("Va__letter.sql") is False

    def test_alphanumeric_version_accepted(self):
        """Only the leading character must be a digit; later segments may mix."""
        assert self.mgr.is_versioned_script_name("V3.2A__mixed.sql") is True

    def test_repeatable_undo_not_versioned(self):
        assert self.mgr.is_versioned_script_name("R__repeat.sql") is False
        assert self.mgr.is_versioned_script_name("U1__undo.sql") is False

    def test_malformed_versioned_no_version(self):
        assert self.mgr.is_versioned_script_name("V__.sql") is False
