"""Cross-directory duplicate-name detection for repeatable migrations.

PR #129 made ``Migration.script_name`` the bare filename for every migration
regardless of which configured directory it came from (previously, scripts
from a secondary ``--scripts`` directory were qualified with their source
directory, which — as an accidental side effect — made their script_name
unique even when two directories held a same-named file). Versioned
migrations already get an equivalent conflict caught by
``_validate_duplicate_versions`` (two scripts can't share a version). But
nothing currently detects two REPEATABLE scripts in different directories
resolving to the identical bare name, e.g. ``migrations/R__cleanup.sql`` vs.
``extra-migrations/R__cleanup.sql`` both becoming ``R__cleanup.sql`` — a
silent collision: whichever is processed last shadows the other's identity
in history.

Mirrors ``tests/unit/core/sql_validator/test_duplicate_version_python_sql.py``,
which exercises ``_validate_duplicate_versions`` the same way for versioned
scripts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.sql_validator.migration_validator import MigrationValidator

pytestmark = [pytest.mark.unit]


def _make_script(name: str, mtype: MigrationType, path: str):
    s = MagicMock()
    s.script_name = name
    s.type = mtype
    s.path = Path(path)
    return s


class _Result:
    def __init__(self):
        self.success = True
        self.error_message = ""


def _validator() -> MigrationValidator:
    # Minimal validator without invoking __init__ (which reaches into
    # config/provider) — only exercises _validate_duplicate_repeatable_names.
    v = MigrationValidator.__new__(MigrationValidator)
    v.log = MagicMock()
    return v


class TestDuplicateRepeatableNameCrossDirectory:
    def test_same_name_different_directory_flagged_as_duplicate(self):
        v = _validator()
        scripts = [
            _make_script(
                "R__cleanup.sql", MigrationType.REPEATABLE, "/proj/migrations/R__cleanup.sql"
            ),
            _make_script(
                "R__cleanup.sql", MigrationType.REPEATABLE, "/proj/extra-migrations/R__cleanup.sql"
            ),
        ]
        result = _Result()
        issues: list = []

        ok = v._validate_duplicate_repeatable_names(scripts, result, issues)

        assert ok is False
        assert result.success is False
        assert any("R__cleanup.sql" in issue for issue in issues)

    def test_distinct_names_ok(self):
        v = _validator()
        scripts = [
            _make_script("R__a.sql", MigrationType.REPEATABLE, "/proj/migrations/R__a.sql"),
            _make_script("R__b.sql", MigrationType.REPEATABLE, "/proj/extra-migrations/R__b.sql"),
        ]
        result = _Result()
        issues: list = []

        ok = v._validate_duplicate_repeatable_names(scripts, result, issues)

        assert ok is True
        assert result.success is True

    def test_same_name_same_path_not_flagged(self):
        """The identical file resolved twice (e.g. duplicated dir config) is
        not a cross-directory collision."""
        v = _validator()
        scripts = [
            _make_script("R__a.sql", MigrationType.REPEATABLE, "/proj/migrations/R__a.sql"),
            _make_script("R__a.sql", MigrationType.REPEATABLE, "/proj/migrations/R__a.sql"),
        ]
        result = _Result()
        issues: list = []

        ok = v._validate_duplicate_repeatable_names(scripts, result, issues)

        assert ok is True

    def test_non_repeatable_types_ignored(self):
        """Versioned/callback scripts sharing a name are out of scope for this
        check (versioned duplicates are already caught by
        _validate_duplicate_versions)."""
        v = _validator()
        scripts = [
            _make_script("V1__a.sql", MigrationType.SQL, "/proj/migrations/V1__a.sql"),
            _make_script("V1__a.sql", MigrationType.SQL, "/proj/extra-migrations/V1__a.sql"),
        ]
        result = _Result()
        issues: list = []

        ok = v._validate_duplicate_repeatable_names(scripts, result, issues)

        assert ok is True


class TestDuplicateRepeatableNameWiredIntoAllRepeatableEarlyReturn:
    """validate_resolved_migrations / validate_migrations short-circuit with
    an early return when every script is REPEATABLE/CALLBACK, *before* the
    point where _validate_duplicate_versions normally runs. A repeatable-only
    secondary-directory migration set is exactly the common case for this
    bug, so the new check must run inside (or before) that early-return path
    — not only in the mixed versioned+repeatable flow."""

    def test_all_repeatable_scripts_with_cross_directory_collision_fail_validation(self):
        v = MigrationValidator.__new__(MigrationValidator)
        v.log = MagicMock()
        v.history_manager = MagicMock()
        v.history_manager.has_history_table = False
        v.script_manager = MagicMock()

        primary = Migration(
            script_name="R__cleanup.sql",
            content="SELECT 1;",
            type=MigrationType.REPEATABLE,
        )
        primary.path = Path("/proj/migrations/R__cleanup.sql")

        secondary = Migration(
            script_name="R__cleanup.sql",
            content="SELECT 2;",
            type=MigrationType.REPEATABLE,
        )
        secondary.path = Path("/proj/extra-migrations/R__cleanup.sql")

        result = v.validate_resolved_migrations([primary, secondary], command="migrate")

        assert result.success is False
        assert any("R__cleanup.sql" in issue for issue in result.issues)
