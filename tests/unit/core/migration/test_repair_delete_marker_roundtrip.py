"""Write/read agreement for the ``[DELETE:TYPE]`` marker.

``repair_command.py`` embeds the original ``MigrationType`` of a missing
script inside the *description* column of the synthetic ``DELETE`` history
row it writes: ``"[DELETE:<TYPE>] <reason>"``. ``data_collector.py`` parses
that marker back out of the description on the read side
(``_get_category_from_type``).

Nothing previously exercised both sides together: ``repair_command``'s own
tests never inspect the description string it produces, and
``data_collector``'s tests hand-craft ``"[DELETE:SQL] ..."`` directly rather
than obtaining it from ``repair_command``. So the two sides could drift apart
silently — e.g. ``repair_command`` could stop writing ``"UNDO_SQL"`` and start
writing ``"UNDO"`` — and the full existing suite would stay green. Confirmed
via mutation: changing the ``"UNDO_SQL"`` literal in the repair command's
type-inference fallback to ``"UNDO"`` passes the pre-existing suite entirely.

This module drives the real write path (``RepairCommand._execute_repair_loop``)
and the real read path (``MigrationDataCollector._get_category_from_type``)
together.
"""

import unittest
from unittest.mock import MagicMock, patch

from dblift.core.logger.results import RepairResult
from dblift.core.migration.commands.repair_command import RepairCommand
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.state.migration_state import MigrationState
from dblift.core.migration.ui.data_collector import MigrationDataCollector
from tests.unit.core.migration.commands._plan_repairs_wiring import as_actions


def _make_repair_cmd():
    """Build a ``RepairCommand`` with minimal mocked collaborators.

    Mirrors ``_make_cmd``/``_make_cmd_for_repair_loop`` in
    ``test_repair_command_extended.py``, duplicated locally so this module
    stays self-contained.
    """
    provider = MagicMock()
    provider.begin_transaction.return_value = None
    provider.commit_transaction.return_value = None

    history_manager = MagicMock()
    history_manager.record_migration.return_value = None
    history_manager.normalized_history_table = "dblift_schema_history"

    config = MagicMock()
    config.database.schema = "public"
    config.database.type = "postgresql"

    cmd = RepairCommand(
        config=config,
        log=MagicMock(),
        provider=provider,
        script_manager=MigrationScriptManager(MagicMock()),
        history_manager=history_manager,
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd, history_manager


def _run_missing_script_repair(script_name: str, original_type):
    """Drive ``_execute_repair_loop`` for a single MISSING_SCRIPT repair and
    return the ``Migration`` handed to ``history_manager.record_migration``."""
    cmd, history_manager = _make_repair_cmd()
    repairs = [
        {
            "type": "MISSING_SCRIPT",
            "script": script_name,
            "version": "1",
            "description": "",
            "original_type": original_type,
        }
    ]
    result = RepairResult()

    with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
        executed, had_error = cmd._execute_repair_loop(
            as_actions(repairs), result, MigrationState()
        )

    assert not had_error, "repair loop reported an error"
    assert executed == 1
    history_manager.record_migration.assert_called_once()
    written_migration = history_manager.record_migration.call_args[0][0]
    return written_migration


# Category the read side (data_collector.py's ``type_to_category``) maps each
# written marker back to. DELETE and BASELINE are filtered out before a
# MISSING_SCRIPT repair is ever generated (repair_command.py, the
# "Skip DELETE and BASELINE type migrations" guard), so they never appear as
# ``original_type`` and are excluded here.
EXPECTED_CATEGORY_BY_MEMBER = {
    MigrationType.SQL: "Versioned",
    MigrationType.PYTHON: "Versioned",
    MigrationType.REPEATABLE: "Repeatable",
    MigrationType.UNDO_SQL: "Undo",
    MigrationType.CALLBACK: "Callback",
    MigrationType.UNKNOWN: "Unknown",  # not in type_to_category -> .capitalize() fallback
}


class TestDeleteMarkerRoundTrip(unittest.TestCase):
    """Write via repair_command, read via data_collector, for every reachable type."""

    def test_written_marker_contains_the_original_type_name(self) -> None:
        for member in EXPECTED_CATEGORY_BY_MEMBER:
            with self.subTest(member=member.name):
                written = _run_missing_script_repair("V1__a.sql", member)
                self.assertIn(f"[DELETE:{member.name}]", written.description)

    def test_written_marker_round_trips_through_data_collector(self) -> None:
        collector = MigrationDataCollector(
            log=MagicMock(), script_manager=MigrationScriptManager(MagicMock())
        )

        for member, expected_category in EXPECTED_CATEGORY_BY_MEMBER.items():
            with self.subTest(member=member.name):
                written = _run_missing_script_repair("V1__a.sql", member)
                category = collector._get_category_from_type("DELETE", migration=written)
                self.assertEqual(category, expected_category)
