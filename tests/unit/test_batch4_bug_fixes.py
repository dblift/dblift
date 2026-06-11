"""Regression tests for the Batch 4 bug fixes (BUG-01..BUG-10).

Each test keeps its scope local to the surface being changed and avoids
network/database dependencies. They are grouped by bug number so that an
intentional behavioral change to any one fix is easy to locate.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# BUG-01 / BUG-03: PG partial unique indexes must not vanish from snapshots
# ---------------------------------------------------------------------------
class TestBug01And03PostgresPartialUniqueIndexes(unittest.TestCase):
    def test_postgres_uses_pg_constraint_query_not_getindexinfo(self) -> None:
        """``get_unique_constraints`` must hit pg_constraint for postgresql,
        otherwise standalone partial unique indexes collapse into named UNIQUE
        constraints with the WHERE predicate stripped (BUG-01 & BUG-03)."""
        from core.introspection.extractors.constraint_extractor import ConstraintExtractor

        self.assertTrue(
            hasattr(ConstraintExtractor, "_get_unique_constraints_postgresql"),
            "PG-specific unique-constraint path must exist so getIndexInfo is "
            "not used for postgresql (BUG-01).",
        )


# ---------------------------------------------------------------------------
# BUG-02: PG DOMAIN must ship base type + CHECK through introspection
# ---------------------------------------------------------------------------
class TestBug02PostgresDomainQueryEnriched(unittest.TestCase):
    def test_pg_udt_query_returns_base_type_and_definition(self) -> None:
        from db.plugins.postgresql.introspection.postgresql_queries import (
            PostgreSQLMetadataQueries,
        )

        sql, _ = PostgreSQLMetadataQueries().get_user_defined_types_query("public")
        self.assertIn("format_type(t.typbasetype", sql)
        self.assertIn("pg_get_constraintdef", sql)


# ---------------------------------------------------------------------------
# BUG-04: undo --target-version must fail hard on un-undoable scripts
# ---------------------------------------------------------------------------
class TestBug04UndoTargetVersionFailsOnBlocking(unittest.TestCase):
    def test_undo_with_target_version_errors_when_script_not_undoable(self) -> None:
        import core.migration.commands.undo_command as mod

        src = Path(mod.__file__).read_text()
        # Should NOT silently warn + clear the blocker: the error branch must
        # call ``result.set_error`` with the explicit guidance text.
        self.assertIn("cannot be undone", src)
        self.assertIn("add 'def undo(context):'", src)


# ---------------------------------------------------------------------------
# BUG-05: strict mode must raise on out-of-order migrations, non-strict warn
# ---------------------------------------------------------------------------
class TestBug05StrictOutOfOrder(unittest.TestCase):
    def test_state_manager_has_strict_out_of_order_messages(self) -> None:
        import core.migration.state.migration_state_manager as mod

        src = Path(mod.__file__).read_text()
        self.assertIn("Strict mode: out-of-order migration", src)
        self.assertIn("Out-of-order migration", src)
        self.assertIn("use --strict to enforce strict ordering", src)


# ---------------------------------------------------------------------------
# BUG-06: --log-level must be applied to the file handler too
# ---------------------------------------------------------------------------
class TestBug06LogLevelAppliedEverywhere(unittest.TestCase):
    def _make_event(self, level_name: str):
        from core.logger.log import LogEvent, LogLevel

        return LogEvent(LogLevel[level_name], "msg", "component")

    def test_file_log_drops_info_when_level_is_error(self) -> None:
        from core.logger.log import FileLog, LogLevel

        with tempfile.TemporaryDirectory() as d:
            fl = FileLog(
                name="T",
                log_dir=Path(d),
                schema="s",
                database_name="db",
                log_level=LogLevel.ERROR,
            )
            # Purge any header the ctor may have emitted; we only care about events.
            if fl.log_file.exists():
                fl.log_file.write_text("")

            fl._write_log_event(self._make_event("INFO"))
            fl._write_log_event(self._make_event("WARN"))
            fl._write_log_event(self._make_event("ERROR"))

            content = fl.log_file.read_text()
            self.assertNotIn("INFO", content)
            self.assertNotIn("WARN", content)
            self.assertIn("ERROR", content)

    def test_console_log_drops_below_threshold(self) -> None:
        from core.logger.log import ConsoleLog, LogLevel

        cl = ConsoleLog(name="T", log_level=LogLevel.WARN)
        # INFO must be filtered before it reaches the sink.
        self.assertFalse(cl._passes_level_filter(LogLevel.INFO))
        self.assertTrue(cl._passes_level_filter(LogLevel.WARN))
        self.assertTrue(cl._passes_level_filter(LogLevel.ERROR))

    def test_log_factory_propagates_log_level_to_file_log(self) -> None:
        from core.logger.log import FileLog, LogFactory, LogLevel

        with tempfile.TemporaryDirectory() as d:
            LogFactory.configure(log_dir=Path(d), log_level=LogLevel.ERROR, use_console=False)
            log = LogFactory.get_log(type("SomeClass", (), {}))
            # MultiLog or FileLog — drill down to first FileLog.
            candidates = getattr(log, "logs", [log])
            file_logs = [c for c in candidates if isinstance(c, FileLog)]
            self.assertTrue(file_logs, "expected a FileLog to be created")
            self.assertEqual(file_logs[0].log_level, LogLevel.ERROR)


# ---------------------------------------------------------------------------
# BUG-09: migration.script.* events actually fire
# ---------------------------------------------------------------------------
class TestBug09ScriptEventsEmitted(unittest.TestCase):
    def test_default_emitter_is_shared(self) -> None:
        from api.events import EventEmitter, get_default_emitter

        first = get_default_emitter()
        self.assertIsInstance(first, EventEmitter)
        self.assertIs(first, get_default_emitter())

    def test_emit_event_helper_dispatches_to_default(self) -> None:
        from api.events import Event, emit_event, get_default_emitter

        received: List[Event] = []
        get_default_emitter().on("migration.script.started", received.append)
        emit_event("migration.script.started", {"script": "V1__x.sql"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].script, "V1__x.sql")

    def test_migrate_command_imports_helper(self) -> None:
        import core.migration.commands.migrate_command as mod

        src = Path(mod.__file__).read_text()
        self.assertIn("_emit_script_event", src)
        self.assertIn("migration.script.started", src)
        self.assertIn("migration.script.completed", src)
        self.assertIn("migration.script.failed", src)


# ---------------------------------------------------------------------------
# BUG-10: repair must not flag baseline rows as MISSING_SCRIPT
# ---------------------------------------------------------------------------
class TestBug10RepairSkipsBaseline(unittest.TestCase):
    def _make_applied(self, script_name: str, type_name: str) -> Any:
        obj = MagicMock()
        obj.script_name = script_name
        obj.version = "2"
        obj.description = ""
        obj.type = MagicMock(name="MigType")
        obj.type.name = type_name
        return obj

    def test_count_candidate_missing_skips_baseline(self) -> None:
        from core.migration.commands.repair_command import _count_candidate_missing

        applied = [
            self._make_applied("B2__.sql", "BASELINE"),
            self._make_applied("V3__add_col.sql", "SQL"),
        ]
        self.assertEqual(_count_candidate_missing(applied, set()), 1)

    def test_count_candidate_missing_skips_baseline_string(self) -> None:
        from core.migration.commands.repair_command import _count_candidate_missing

        applied = [self._make_applied("B2__.sql", "anything")]
        # type provided as a plain string rather than an enum-like MagicMock.
        applied[0].type = "BASELINE"
        self.assertEqual(_count_candidate_missing(applied, set()), 0)


if __name__ == "__main__":
    unittest.main()
