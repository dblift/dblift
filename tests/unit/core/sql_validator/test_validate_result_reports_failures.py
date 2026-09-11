"""A failed validation must name the migrations that failed, not just say it failed.

``ValidateResult`` has carried ``error_count`` / ``validated_migrations`` /
``failed_migrations`` since it was written, and nothing ever populated them, so
``validate --format json`` answered ``error_count: 0`` with two empty lists on a
run the console reported as failed — and the ``error`` string carried only the
first issue, dropping every later one.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.cli.handlers.validate import _validate_result_to_dict
from dblift.core.logger.results import ValidateResult
from dblift.core.migration.commands.validate_command import ValidateCommand
from dblift.core.sql_validator.migration_validator import ValidationResult


def _script(name: str, version: str):
    m = MagicMock()
    m.script_name = name
    m.version = version
    m.description = name.split("__", 1)[-1].rsplit(".", 1)[0]
    m.type = "SQL"
    m.checksum = 1
    return m


def _command_with(validation_result: ValidationResult) -> ValidateCommand:
    cmd = ValidateCommand.__new__(ValidateCommand)
    cmd.config = MagicMock()
    cmd.config.database.schema = "main"
    cmd.log = MagicMock()
    cmd.validator = MagicMock()
    cmd.validator.validate_migrations.return_value = validation_result
    cmd.history_manager = MagicMock()
    cmd._populate_database_info = MagicMock()
    cmd._log_command_header_update = MagicMock()
    cmd._log_command_completion = MagicMock()
    cmd._execute_callbacks = MagicMock()
    return cmd


@pytest.mark.unit
def test_failed_validation_names_every_failing_migration():
    """Two drifted scripts: both must reach the result, not only the first."""
    vr = ValidationResult()
    vr.success = False
    vr.migrations = [_script("V1__a.sql", "1"), _script("V2__b.sql", "2"), _script("V3__c.sql", "3")]
    vr.issues = [
        "Migration script V1__a.sql has been modified since it was applied.",
        "Migration script V3__c.sql has been modified since it was applied.",
        "Validation failed. Detected modified migration scripts.",
    ]
    vr.error_message = vr.issues[0]
    vr.failed_scripts = ["V1__a.sql", "V3__c.sql"]

    result = _command_with(vr).execute(Path("/tmp/migrations"))

    assert result.success is False
    assert {m.script for m in result.failed_migrations} == {"V1__a.sql", "V3__c.sql"}
    assert {m.script for m in result.validated_migrations} == {"V2__b.sql"}
    assert result.error_count == 2


@pytest.mark.unit
def test_json_payload_carries_the_failures_and_every_issue():
    """The JSON consumer must see what the console prints."""
    vr = ValidationResult()
    vr.success = False
    vr.migrations = [_script("V1__a.sql", "1"), _script("V3__c.sql", "3")]
    vr.issues = [
        "Migration script V1__a.sql has been modified since it was applied.",
        "Migration script V3__c.sql has been modified since it was applied.",
    ]
    vr.error_message = vr.issues[0]
    vr.failed_scripts = ["V1__a.sql", "V3__c.sql"]

    payload = _validate_result_to_dict(_command_with(vr).execute(Path("/tmp/migrations")))

    assert payload["success"] is False
    assert payload["error_count"] == 2, "error_count must not contradict success: false"
    assert [m["script"] for m in payload["failed_migrations"]] == ["V1__a.sql", "V3__c.sql"]
    # Every issue the console logged is reachable, not just the first.
    assert payload["issues"] == vr.issues


@pytest.mark.unit
def test_successful_validation_lists_what_it_validated():
    vr = ValidationResult()
    vr.success = True
    vr.migrations = [_script("V1__a.sql", "1"), _script("V2__b.sql", "2")]

    result = _command_with(vr).execute(Path("/tmp/migrations"))

    assert result.success is True
    assert result.error_count == 0
    assert result.failed_migrations == []
    assert {m.script for m in result.validated_migrations} == {"V1__a.sql", "V2__b.sql"}


@pytest.mark.unit
def test_add_failed_migration_still_drives_count_and_success():
    """The existing ValidateResult contract stays intact."""
    r = ValidateResult()
    assert r.success is True and r.error_count == 0

    r.add_failed_migration(MagicMock())

    assert r.success is False and r.error_count == 1
