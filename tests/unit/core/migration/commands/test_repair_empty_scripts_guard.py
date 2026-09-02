"""Regression coverage for BUG-04: repair mass-marks applied migrations as MISSING
when the scripts directory is empty.

Scenario: the user invokes ``repair`` without ``--scripts``; the default
resolves to ``<cwd>/migrations`` which is typically empty. The previous
behaviour silently treated every applied migration as "script file gone"
and produced one MISSING_SCRIPT repair per applied row — and without
``--dry-run`` those converted to DELETE history entries, effectively
orphaning the migration table. A silent false-positive factory.

This test constructs a minimally-wired RepairCommand (the detection
method itself only needs a ``script_manager`` and a ``log``) and asserts
that the new safety gate refuses to mass-mark when no filesystem scripts
are visible.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.repair_command import RepairCommand, RepairSafetyError
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.migration_state import MigrationState


def _make_applied(script_name: str, version: str = "1") -> SimpleNamespace:
    """Minimal applied-migration stand-in (matches attribute access in code under test)."""
    return SimpleNamespace(
        script_name=script_name,
        version=version,
        description="",
        type=SimpleNamespace(name="VERSIONED"),
    )


def _make_repair_command(script_manager_mock: MagicMock) -> RepairCommand:
    """Bypass BaseCommand.__init__ — we only exercise _detect_missing_migrations.

    ``_detect_missing_migrations`` uses two attributes: ``script_manager``
    and ``log``. Everything else on the instance is irrelevant for this
    path, so constructing without running BaseCommand's heavy init keeps
    the test hermetic.
    """
    cmd = RepairCommand.__new__(RepairCommand)
    cmd.script_manager = script_manager_mock
    cmd.log = MagicMock()
    return cmd


@pytest.mark.unit
class TestRepairEmptyScriptsGuard:
    def test_refuses_when_no_scripts_and_applied_migrations_present(self, tmp_path: Path):
        """BUG-04: empty filesystem + applied migrations must raise, not mass-mark."""
        script_manager = MagicMock()
        script_manager.load_migration_scripts.return_value = {}  # empty dict, no migrations

        cmd = _make_repair_command(script_manager)
        state = MigrationState(
            applied_objects=[
                _make_applied("V1__a.sql", "1"),
                _make_applied("V2__b.sql", "2"),
                _make_applied("V3__c.sql", "3"),
            ],
        )

        with pytest.raises(RepairSafetyError) as exc_info:
            cmd._detect_missing_migrations(state, tmp_path)

        msg = str(exc_info.value)
        assert "3" in msg, "error message should say how many migrations would be affected"
        assert "--scripts" in msg, "error should hint at the --scripts fix"

    def test_noop_when_no_scripts_and_no_applied_migrations(self, tmp_path: Path):
        """Empty filesystem + empty history = nothing to do; no false alarm."""
        script_manager = MagicMock()
        script_manager.load_migration_scripts.return_value = {}

        cmd = _make_repair_command(script_manager)
        state = MigrationState(applied_objects=[])

        # Should not raise; returns an empty repair list.
        repairs = cmd._detect_missing_migrations(state, tmp_path)
        assert repairs == []

    def test_happy_path_still_flags_genuinely_missing_script(self, tmp_path: Path):
        """One applied script absent + one applied script present → flag only the absent one."""
        script_manager = MagicMock()
        # Filesystem has V1 only; applied has V1 + V2.
        present = SimpleNamespace(script_name="V1__a.sql")
        script_manager.load_migration_scripts.return_value = {"V1": [present]}

        cmd = _make_repair_command(script_manager)
        state = MigrationState(
            applied_objects=[
                _make_applied("V1__a.sql", "1"),
                _make_applied("V2__b.sql", "2"),  # missing on disk
            ],
        )

        repairs = cmd._detect_missing_migrations(state, tmp_path)
        missing_scripts: List[str] = [r["script"] for r in repairs if r["type"] == "MISSING_SCRIPT"]
        assert missing_scripts == ["V2__b.sql"]

    def test_load_failure_propagates_instead_of_silent_empty(self, tmp_path: Path):
        """Script-manager load failure must not silently become 'zero scripts'."""
        script_manager = MagicMock()
        script_manager.load_migration_scripts.side_effect = PermissionError(
            "cannot read scripts dir"
        )

        cmd = _make_repair_command(script_manager)
        state = MigrationState(
            applied_objects=[_make_applied("V1__a.sql", "1")],
        )

        with pytest.raises(PermissionError):
            cmd._detect_missing_migrations(state, tmp_path)


@pytest.mark.unit
class TestRepairChecksumDrift:
    def test_zero_checksum_is_compared_instead_of_skipped(self, tmp_path: Path):
        """A stored checksum of 0 is still a real value for drift detection."""
        script_manager = MagicMock()
        script_manager.load_migration_scripts.return_value = {
            "1": [SimpleNamespace(script_name="V1__a.sql", checksum=123)]
        }
        cmd = _make_repair_command(script_manager)
        state = MigrationState(
            all_applied_objects=[
                SimpleNamespace(
                    script_name="V1__a.sql",
                    version="1",
                    type=MigrationType.SQL,
                    checksum=0,
                )
            ]
        )

        repairs = cmd._detect_checksum_drift(state, [], tmp_path)

        assert repairs == [
            {
                "type": "CHECKSUM_MISMATCH",
                "script": "V1__a.sql",
                "old_checksum": 0,
                "new_checksum": 123,
            }
        ]
