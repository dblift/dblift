"""BUG-02 regression: duplicate version detection must span SQL + PYTHON.

Before the fix, ``_validate_duplicate_versions`` counted only
``MigrationType.SQL`` and fell through to ``continue`` for
``MigrationType.PYTHON``. A ``V1__a.sql`` + ``V1__b.py`` pair was
silently accepted and both applied — CosmosDB surfaced the symptom
most visibly. The fix treats SQL and PYTHON as one versioned track.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.sql_validator.migration_validator import MigrationValidator


def _make_script(version: str, name: str, mtype: MigrationType):
    s = MagicMock()
    s.version = version
    s.script_name = name
    s.type = mtype
    return s


class _Result:
    def __init__(self):
        self.success = True
        self.error_message = ""


@pytest.mark.unit
class TestDuplicateVersionSqlPython:
    def _validator(self) -> MigrationValidator:
        # Build a minimal validator without invoking __init__ (which reaches
        # into config/provider). We only exercise _validate_duplicate_versions.
        v = MigrationValidator.__new__(MigrationValidator)
        v.log = MagicMock()
        return v

    def test_v1_sql_and_v1_python_flagged_as_duplicate(self):
        v = self._validator()
        scripts = [
            _make_script("1", "V1__containers.sql", MigrationType.SQL),
            _make_script("1", "V1__create_containers.py", MigrationType.PYTHON),
        ]
        result = _Result()
        issues: list[str] = []

        ok = v._validate_duplicate_versions(scripts, result, issues)

        assert ok is False
        assert result.success is False
        assert "duplicate" in (result.error_message or "").lower() or issues

    def test_two_python_same_version_flagged(self):
        v = self._validator()
        scripts = [
            _make_script("2", "V2__a.py", MigrationType.PYTHON),
            _make_script("2", "V2__b.py", MigrationType.PYTHON),
        ]
        result = _Result()
        issues: list[str] = []

        ok = v._validate_duplicate_versions(scripts, result, issues)

        assert ok is False

    def test_distinct_versions_sql_and_python_ok(self):
        v = self._validator()
        scripts = [
            _make_script("1", "V1__a.sql", MigrationType.SQL),
            _make_script("2", "V2__b.py", MigrationType.PYTHON),
        ]
        result = _Result()
        issues: list[str] = []

        ok = v._validate_duplicate_versions(scripts, result, issues)

        assert ok is True
        assert result.success is True

    def test_baseline_can_coexist_with_python_same_version(self):
        """Pre-existing BASELINE exception must still hold — now for PYTHON too."""
        v = self._validator()
        scripts = [
            _make_script("1", "B1__baseline.sql", MigrationType.BASELINE),
            _make_script("1", "V1__x.py", MigrationType.PYTHON),
        ]
        result = _Result()
        issues: list[str] = []

        ok = v._validate_duplicate_versions(scripts, result, issues)

        assert ok is True
