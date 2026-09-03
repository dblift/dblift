"""Cross-directory duplicate-version error message must be disambiguated.

``_validate_duplicate_versions`` reports a collision using
``Migration.script_name``, which (per PR #129) is always the bare filename
regardless of which configured ``--scripts`` directory it came from. When two
directories each contain a same-named file for the same version (e.g.
``migrations/V100__dup.sql`` vs. ``extra-migrations/V100__dup.sql``), the
error message repeats the identical basename twice with no way to tell the
two colliding files apart. ``_validate_duplicate_repeatable_names`` already
solves the equivalent problem for repeatable migrations by including
``Migration.path`` in its message; this mirrors that fix for versioned
migrations.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.sql_validator.migration_validator import MigrationValidator

pytestmark = [pytest.mark.unit]


def _make_script(version: str, name: str, mtype: MigrationType, path: str):
    s = MagicMock()
    s.version = version
    s.script_name = name
    s.type = mtype
    s.path = Path(path)
    return s


class _Result:
    def __init__(self):
        self.success = True
        self.error_message = ""


def _validator() -> MigrationValidator:
    v = MigrationValidator.__new__(MigrationValidator)
    v.log = MagicMock()
    return v


class TestDuplicateVersionCrossDirectoryErrorMessage:
    def test_error_message_includes_both_full_paths(self):
        v = _validator()
        scripts = [
            _make_script(
                "100", "V100__dup_test.sql", MigrationType.SQL, "/proj/scripts_a/V100__dup_test.sql"
            ),
            _make_script(
                "100", "V100__dup_test.sql", MigrationType.SQL, "/proj/scripts_b/V100__dup_test.sql"
            ),
        ]
        result = _Result()
        issues: list = []

        ok = v._validate_duplicate_versions(scripts, result, issues)

        assert ok is False
        assert result.success is False
        assert "/proj/scripts_a/V100__dup_test.sql" in result.error_message
        assert "/proj/scripts_b/V100__dup_test.sql" in result.error_message
