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
together, and separately pins the fallback type inference (used when no
``original_type`` object is available) against the ``MigrationType`` enum
rather than the hardcoded literal strings it previously duplicated.
"""

import unittest
from unittest.mock import MagicMock, patch

from dblift.core.logger.results import RepairResult
from dblift.core.migration.commands.repair_command import RepairCommand
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.ui.data_collector import MigrationDataCollector


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
        script_manager=MagicMock(),
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
        executed, had_error = cmd._execute_repair_loop(repairs, result)

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
        collector = MigrationDataCollector(log=MagicMock())

        for member, expected_category in EXPECTED_CATEGORY_BY_MEMBER.items():
            with self.subTest(member=member.name):
                written = _run_missing_script_repair("V1__a.sql", member)
                category = collector._get_category_from_type("DELETE", migration=written)
                self.assertEqual(category, expected_category)


class TestMissingScriptFallbackTypeInference(unittest.TestCase):
    """When no ``original_type`` is available, repair_command infers the type
    from the script name's Flyway-style prefix (V/R/U).

    Pins the inferred marker strings against ``MigrationType`` member names
    rather than the literal strings the production code previously
    hardcoded in this branch, so a rename of e.g. ``MigrationType.UNDO_SQL``
    changes this test's expectation instead of leaving a now-wrong literal
    behind silently.
    """

    def test_v_prefix_infers_sql(self) -> None:
        written = _run_missing_script_repair("V1__a.sql", None)
        self.assertIn(f"[DELETE:{MigrationType.SQL.name}]", written.description)

    def test_r_prefix_infers_repeatable(self) -> None:
        written = _run_missing_script_repair("R__a.sql", None)
        self.assertIn(f"[DELETE:{MigrationType.REPEATABLE.name}]", written.description)

    def test_u_prefix_infers_undo_sql(self) -> None:
        written = _run_missing_script_repair("U1__a.sql", None)
        self.assertIn(f"[DELETE:{MigrationType.UNDO_SQL.name}]", written.description)

    def test_unrecognised_prefix_falls_back_to_sql(self) -> None:
        written = _run_missing_script_repair("X__a.sql", None)
        self.assertIn(f"[DELETE:{MigrationType.SQL.name}]", written.description)


class TestWriteBranchDisagreement(unittest.TestCase):
    """Documents a real disagreement between the two write branches for a
    versioned Python script, rather than papering over it.

    When ``original_type`` is available, a versioned ``.py`` script is typed
    ``PYTHON`` (``Migration.type`` rewrites ``SQL`` to ``PYTHON`` for
    non-SQL scripted formats — see ``test_path_constructed_migration_type``
    in ``test_persisted_type_vocabulary.py``). But the *fallback* branch,
    used when ``original_type`` is unavailable, infers purely from the
    ``V``/``R``/``U`` filename prefix and cannot distinguish ``.py`` from
    ``.sql`` — a ``V1__x.py`` falling into the fallback is marked ``SQL``,
    not ``PYTHON``. Same logical migration, two different markers depending
    on whether the history row still carried a ``type``. This is a narrow,
    pre-existing gap (the fallback only fires when the applied migration
    object itself doesn't have the type attribute) and is left as-is per the
    scope of this change; documented here so it isn't silently masked.
    """

    def test_python_original_type_and_py_fallback_disagree(self) -> None:
        with_type = _run_missing_script_repair("V1__x.py", MigrationType.PYTHON)
        without_type = _run_missing_script_repair("V1__x.py", None)

        self.assertIn("[DELETE:PYTHON]", with_type.description)
        self.assertIn("[DELETE:SQL]", without_type.description)
        self.assertNotEqual(with_type.description, without_type.description)
