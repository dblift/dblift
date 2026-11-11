"""Checksum validation leaves undo history rows alone, however their type is spelled."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.migration import MigrationType
from dblift.core.sql_validator._checksum_validator import validate_checksums
from dblift.core.sql_validator.migration_validator import MigrationValidator, ValidationResult

pytestmark = [pytest.mark.unit]


def _validator() -> MigrationValidator:
    instance = MigrationValidator.__new__(MigrationValidator)
    instance.log = NullLog()
    return instance


def _row(name: str, migration_type: object) -> SimpleNamespace:
    return SimpleNamespace(script_name=name, type=migration_type, success=True, version="1")


@pytest.mark.parametrize("undo_type", ["UNDO_SQL", MigrationType.UNDO_SQL])
def test_an_undo_row_is_not_checked(undo_type):
    scripts = [SimpleNamespace(script_name="V1__a.sql", version="1")]
    rows = [_row("V1__a.sql", MigrationType.SQL), _row("U1__a.sql", undo_type)]
    result, issues = ValidationResult(), []
    validate_checksums(_validator(), scripts, rows, result, issues, drift=(), missing=())
    assert result.checked_scripts == ["V1__a.sql"]
    assert issues == []
