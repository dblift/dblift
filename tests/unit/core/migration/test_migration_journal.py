"""Tests for core.migration.journals.migration_journal module."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.journals.migration_journal import (
    EntryType,
    JournalEntry,
    MigrationJournal,
)

# ---------------------------------------------------------------------------
# EntryType enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEntryType:
    """Verify all expected enum members exist."""

    def test_all_members(self):
        expected = {
            "STATEMENT_START",
            "STATEMENT_COMPLETE",
            "STATEMENT_FAILED",
            "MIGRATION_START",
            "MIGRATION_COMPLETE",
            "MIGRATION_FAILED",
            "OBJECT_CHANGE",
        }
        assert {e.value for e in EntryType} == expected

    def test_value_equals_name(self):
        for member in EntryType:
            assert member.value == member.name


# ---------------------------------------------------------------------------
# JournalEntry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJournalEntry:
    """Tests for JournalEntry construction."""

    def test_constructor_defaults(self):
        before = datetime.now()
        entry = JournalEntry(migration_id="V1__init.sql", entry_type=EntryType.STATEMENT_START)
        after = datetime.now()

        assert entry.migration_id == "V1__init.sql"
        assert entry.entry_type == EntryType.STATEMENT_START
        assert entry.statement_index == 0
        assert entry.statement == ""
        assert entry.execution_time == 0
        assert before <= entry.timestamp <= after
        assert entry.details == {}
        assert entry.success is True
        assert entry.error_message == ""

    def test_constructor_explicit_values(self):
        ts = datetime(2026, 1, 15, 10, 30, 0)
        entry = JournalEntry(
            migration_id="V2__add_col.sql",
            entry_type=EntryType.STATEMENT_FAILED,
            statement_index=3,
            statement="ALTER TABLE t ADD col INT",
            execution_time=150,
            timestamp=ts,
            details={"affected_rows": 0},
            success=False,
            error_message="column already exists",
        )
        assert entry.timestamp == ts
        assert entry.details == {"affected_rows": 0}
        assert entry.success is False
        assert entry.error_message == "column already exists"


# ---------------------------------------------------------------------------
# MigrationJournal — disabled journal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigrationJournalDisabled:
    """When disabled, all record methods are no-ops."""

    def test_init_disabled(self):
        j = MigrationJournal(enabled=False)
        assert j.enabled is False
        assert j.current_migration_id is None
        assert j.entries == []

    def test_start_migration_noop(self):
        j = MigrationJournal(enabled=False)
        j.start_migration("V1__init.sql")
        assert j.current_migration_id is None
        assert j.entries == []

    def test_record_statement_start_noop(self):
        j = MigrationJournal(enabled=False)
        j.record_statement_start("SELECT 1", 0)
        assert j.entries == []

    def test_record_statement_complete_noop(self):
        j = MigrationJournal(enabled=False)
        j.record_statement_complete("SELECT 1", 0, 10)
        assert j.entries == []

    def test_record_statement_failed_noop(self):
        j = MigrationJournal(enabled=False)
        j.record_statement_failed("SELECT 1", 0, "err")
        assert j.entries == []

    def test_record_object_changes_noop(self):
        j = MigrationJournal(enabled=False)
        j.record_object_changes("CREATE TABLE t (id INT)", 0, [])
        assert j.entries == []

    def test_get_migration_journal_returns_empty(self):
        j = MigrationJournal(enabled=False)
        assert j.get_migration_journal("V1__init.sql") == []


# ---------------------------------------------------------------------------
# MigrationJournal — guards (no current migration)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigrationJournalGuards:
    """record_* methods are no-ops when there is no active migration."""

    def _make_journal(self):
        j = MigrationJournal(enabled=True)
        # Do NOT call start_migration, so current_migration_id is None
        return j

    def test_record_statement_start_no_migration(self):
        j = self._make_journal()
        j.record_statement_start("SELECT 1", 0)
        assert j.entries == []

    def test_record_statement_complete_no_migration(self):
        j = self._make_journal()
        j.record_statement_complete("SELECT 1", 0, 10)
        assert j.entries == []

    def test_record_statement_failed_no_migration(self):
        j = self._make_journal()
        j.record_statement_failed("SELECT 1", 0, "err")
        assert j.entries == []

    def test_record_object_changes_no_migration(self):
        j = self._make_journal()
        j.record_object_changes("CREATE TABLE t (id INT)", 0, [])
        assert j.entries == []


# ---------------------------------------------------------------------------
# MigrationJournal — full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigrationJournalLifecycle:
    """Full migration lifecycle: start -> statements -> end."""

    def test_full_success_lifecycle(self):
        j = MigrationJournal()
        mid = "V1__init.sql"

        j.start_migration(mid, details={"version": "1"})
        assert j.current_migration_id == mid

        j.record_statement_start("CREATE TABLE t (id INT)", 0)
        j.record_statement_complete("CREATE TABLE t (id INT)", 0, 50, {"affected_rows": 0})
        j.record_statement_start("INSERT INTO t VALUES (1)", 1)
        j.record_statement_complete("INSERT INTO t VALUES (1)", 1, 10, {"affected_rows": 1})

        j.end_migration(mid, success=True, execution_time=60)
        assert j.current_migration_id is None

        entries = j.get_migration_journal(mid)
        types = [e.entry_type for e in entries]
        assert types[0] == EntryType.MIGRATION_START
        assert EntryType.STATEMENT_START in types
        assert EntryType.STATEMENT_COMPLETE in types
        assert types[-1] == EntryType.MIGRATION_COMPLETE

    def test_full_failure_lifecycle(self):
        j = MigrationJournal()
        mid = "V2__bad.sql"

        j.start_migration(mid)
        j.record_statement_start("DROP TABLE nonexistent", 0)
        j.record_statement_failed("DROP TABLE nonexistent", 0, "table not found", 5)
        j.end_migration(mid, success=False, error_message="migration failed", execution_time=5)

        assert j.current_migration_id is None
        entries = j.get_migration_journal(mid)
        fail_entries = [e for e in entries if e.entry_type == EntryType.MIGRATION_FAILED]
        assert len(fail_entries) == 1
        assert fail_entries[0].success is False
        assert fail_entries[0].error_message == "migration failed"


# ---------------------------------------------------------------------------
# MigrationJournal — end_migration edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEndMigrationEdgeCases:
    """end_migration guards: mismatch and no current migration."""

    def test_end_migration_no_current_is_noop(self):
        j = MigrationJournal()
        j.end_migration("V1__init.sql", success=True)
        assert j.entries == []

    def test_end_migration_mismatch_is_noop(self):
        j = MigrationJournal()
        j.start_migration("V1__init.sql")
        initial_count = len(j.entries)

        j.end_migration("V2__other.sql", success=True)
        # current_migration_id should remain unchanged
        assert j.current_migration_id == "V1__init.sql"
        # No new entries beyond the MIGRATION_START
        assert len(j.entries) == initial_count


# ---------------------------------------------------------------------------
# MigrationJournal — _write_entry deduplication
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteEntryDeduplication:
    """_write_entry removes duplicates for end entries and statement entries."""

    def test_duplicate_migration_complete_replaces(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)
        j.end_migration(mid, success=True, execution_time=10)

        # Manually re-start to force a second end
        j.current_migration_id = mid
        j.end_migration(mid, success=True, execution_time=20)

        mig_entries = j.get_migration_journal(mid)
        complete_entries = [e for e in mig_entries if e.entry_type == EntryType.MIGRATION_COMPLETE]
        assert len(complete_entries) == 1
        assert complete_entries[0].execution_time == 20

    def test_duplicate_statement_complete_same_index_replaces(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        j.record_statement_complete("CREATE TABLE t (id INT)", 0, 50)
        j.record_statement_complete("CREATE TABLE t (id INT)", 0, 75)

        mig_entries = j.get_migration_journal(mid)
        stmt_complete = [
            e
            for e in mig_entries
            if e.entry_type == EntryType.STATEMENT_COMPLETE and e.statement_index == 0
        ]
        assert len(stmt_complete) == 1
        assert stmt_complete[0].execution_time == 75

    def test_duplicate_statement_start_same_index_replaces(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        j.record_statement_start("SELECT 1", 0)
        j.record_statement_start("SELECT 1", 0)

        mig_entries = j.get_migration_journal(mid)
        stmt_start = [
            e
            for e in mig_entries
            if e.entry_type == EntryType.STATEMENT_START and e.statement_index == 0
        ]
        assert len(stmt_start) == 1

    def test_different_statement_indexes_not_deduplicated(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        j.record_statement_complete("CREATE TABLE a (id INT)", 0, 10)
        j.record_statement_complete("CREATE TABLE b (id INT)", 1, 20)

        mig_entries = j.get_migration_journal(mid)
        stmt_complete = [e for e in mig_entries if e.entry_type == EntryType.STATEMENT_COMPLETE]
        assert len(stmt_complete) == 2


# ---------------------------------------------------------------------------
# _determine_operation_from_statement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetermineOperationFromStatement:
    """Tests for SQL operation detection."""

    @pytest.fixture
    def journal(self):
        return MigrationJournal()

    @pytest.mark.parametrize(
        "statement, expected",
        [
            ("CREATE TABLE t (id INT)", "CREATE"),
            ("CREATE INDEX idx ON t(col)", "CREATE"),
            ("ALTER TABLE t ADD col INT", "ALTER"),
            ("DROP TABLE t", "DROP"),
            ("INSERT INTO t VALUES (1)", "INSERT"),
            ("UPDATE t SET col = 1", "UPDATE"),
            ("DELETE FROM t WHERE id = 1", "DELETE"),
            ("COMMENT ON TABLE t IS 'desc'", "COMMENT"),
            ("TRUNCATE TABLE t", "TRUNCATE"),
            ("GRANT SELECT ON t TO user1", "GRANT"),
            ("REVOKE SELECT ON t FROM user1", "REVOKE"),
            ("SELECT id FROM users", "SELECT"),
            ("WITH cte AS (SELECT 1) SELECT * FROM users", "SELECT"),
        ],
    )
    def test_known_operations(self, journal, statement, expected):
        assert journal._determine_operation_from_statement(statement) == expected

    def test_case_insensitive(self, journal):
        assert journal._determine_operation_from_statement("  create table t (id int)") == "CREATE"
        assert journal._determine_operation_from_statement("  drop TABLE t") == "DROP"

    def test_empty_string_returns_unknown(self, journal):
        assert journal._determine_operation_from_statement("") == "UNKNOWN"

    def test_unrecognized_returns_unknown(self, journal):
        assert journal._determine_operation_from_statement("EXEC sp_do_stuff") == "UNKNOWN"

    def test_object_type_param_accepted(self, journal):
        # object_type does not change the result, but must be accepted
        assert (
            journal._determine_operation_from_statement("CREATE TABLE t (id INT)", "TABLE")
            == "CREATE"
        )


# ---------------------------------------------------------------------------
# record_object_changes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordObjectChanges:
    """Tests for record_object_changes entry creation."""

    def test_records_object_change_entry(self):
        j = MigrationJournal()
        j.start_migration("V1__init.sql")
        objects = [{"object_type": "TABLE", "object_name": "users"}]
        j.record_object_changes("CREATE TABLE users (id INT)", 0, objects)

        entries = j.get_migration_journal("V1__init.sql")
        oc = [e for e in entries if e.entry_type == EntryType.OBJECT_CHANGE]
        assert len(oc) == 1
        assert oc[0].details["objects_affected"] == objects
        assert oc[0].statement == "CREATE TABLE users (id INT)"
        assert oc[0].statement_index == 0


# ---------------------------------------------------------------------------
# get_performance_stats_by_object_type
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPerformanceStatsByObjectType:
    """Tests for performance grouping by object type."""

    def test_empty_journal_returns_empty(self):
        j = MigrationJournal()
        assert j.get_performance_stats_by_object_type("V1__init.sql") == {}

    def test_no_object_change_entries_returns_empty(self):
        j = MigrationJournal()
        j.start_migration("V1__init.sql")
        j.record_statement_complete("SELECT 1", 0, 10)
        j.end_migration("V1__init.sql", success=True)
        assert j.get_performance_stats_by_object_type("V1__init.sql") == {}

    def test_object_change_without_matching_statement_complete_skipped(self):
        j = MigrationJournal()
        j.start_migration("V1__init.sql")
        # OBJECT_CHANGE at index 5, but no STATEMENT_COMPLETE at index 5
        j.record_object_changes(
            "CREATE TABLE t (id INT)", 5, [{"object_type": "TABLE", "object_name": "t"}]
        )
        j.end_migration("V1__init.sql", success=True)
        assert j.get_performance_stats_by_object_type("V1__init.sql") == {}

    def test_stats_calculated_correctly(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        # Statement 0: CREATE TABLE users — 100ms
        j.record_statement_complete("CREATE TABLE users (id INT)", 0, 100)
        j.record_object_changes(
            "CREATE TABLE users (id INT)", 0, [{"object_type": "TABLE", "object_name": "users"}]
        )

        # Statement 1: CREATE TABLE orders — 200ms
        j.record_statement_complete("CREATE TABLE orders (id INT)", 1, 200)
        j.record_object_changes(
            "CREATE TABLE orders (id INT)", 1, [{"object_type": "TABLE", "object_name": "orders"}]
        )

        # Statement 2: CREATE INDEX idx — 50ms
        j.record_statement_complete("CREATE INDEX idx ON users(id)", 2, 50)
        j.record_object_changes(
            "CREATE INDEX idx ON users(id)", 2, [{"object_type": "INDEX", "object_name": "idx"}]
        )

        j.end_migration(mid, success=True)

        stats = j.get_performance_stats_by_object_type(mid)

        assert "TABLE" in stats
        assert stats["TABLE"]["count"] == 2
        assert stats["TABLE"]["total_time"] == 300
        assert stats["TABLE"]["max_time"] == 200
        assert stats["TABLE"]["avg_time"] == 150.0
        assert set(stats["TABLE"]["objects"]) == {"users", "orders"}

        assert "INDEX" in stats
        assert stats["INDEX"]["count"] == 1
        assert stats["INDEX"]["total_time"] == 50
        assert stats["INDEX"]["objects"] == ["idx"]


# ---------------------------------------------------------------------------
# get_migration_performance_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMigrationPerformanceSummary:
    """Tests for the full performance summary."""

    def test_empty_journal_returns_empty(self):
        j = MigrationJournal()
        assert j.get_migration_performance_summary("V1__init.sql") == {}

    def test_no_statement_times_returns_zeroed_summary(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid, details={"version": "1"})
        j.end_migration(mid, success=True)

        summary = j.get_migration_performance_summary(mid)
        assert summary["migration_id"] == mid
        assert summary["version"] == "1"
        assert summary["total_statements"] == 0
        assert summary["total_execution_time"] == 0
        assert summary["slowest_statement"] is None
        assert summary["statements"] == []
        assert summary["object_operations"] == []

    def test_summary_with_statements(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid, details={"version": "1"})

        j.record_statement_complete("CREATE TABLE t (id INT)", 0, 100)
        j.record_statement_complete("INSERT INTO t VALUES (1)", 1, 30)
        j.end_migration(mid, success=True, execution_time=130)

        summary = j.get_migration_performance_summary(mid)
        assert summary["migration_id"] == mid
        assert summary["version"] == "1"
        assert summary["total_statements"] == 2
        assert summary["total_execution_time"] == 130
        assert summary["avg_statement_time"] == 65.0
        assert summary["max_statement_time"] == 100
        assert summary["min_statement_time"] == 30
        assert summary["slowest_statement"] == "CREATE TABLE t (id INT)"
        assert len(summary["statements"]) == 2

    def test_summary_with_object_operations_dict_form(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        j.record_statement_complete("CREATE TABLE users (id INT)", 0, 50)
        j.record_object_changes(
            "CREATE TABLE users (id INT)",
            0,
            [{"object_type": "TABLE", "object_name": "users", "schema": "public"}],
        )
        j.end_migration(mid, success=True)

        summary = j.get_migration_performance_summary(mid)
        assert len(summary["object_operations"]) == 1
        op = summary["object_operations"][0]
        assert op["operation"] == "CREATE"
        assert op["object_type"] == "TABLE"
        assert op["object_name"] == "users"
        assert op["schema"] == "public"

    def test_summary_with_object_operations_object_form(self):
        """SqlObject-like instances (non-dict) are handled via getattr."""
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        sql_obj = MagicMock()
        sql_obj.name = "orders"
        sql_obj.schema = "sales"
        sql_obj.object_type = "TABLE"

        j.record_statement_complete("DROP TABLE sales.orders", 0, 20)
        # Manually inject an OBJECT_CHANGE with a non-dict object
        entry = JournalEntry(
            migration_id=mid,
            entry_type=EntryType.OBJECT_CHANGE,
            statement="DROP TABLE sales.orders",
            statement_index=0,
            details={"objects_affected": [sql_obj]},
        )
        j._write_entry(entry)
        j.end_migration(mid, success=True)

        summary = j.get_migration_performance_summary(mid)
        assert len(summary["object_operations"]) == 1
        op = summary["object_operations"][0]
        assert op["operation"] == "DROP"
        assert op["object_type"] == "TABLE"
        assert op["object_name"] == "orders"
        assert op["schema"] == "sales"

    def test_summary_strips_schema_prefix_from_object_name(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        j.record_statement_complete("CREATE TABLE public.t (id INT)", 0, 10)
        j.record_object_changes(
            "CREATE TABLE public.t (id INT)",
            0,
            [{"object_type": "TABLE", "object_name": "public.t", "schema": "public"}],
        )
        j.end_migration(mid, success=True)

        summary = j.get_migration_performance_summary(mid)
        op = summary["object_operations"][0]
        assert op["object_name"] == "t"

    def test_summary_version_none(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)  # no details, no version
        j.record_statement_complete("SELECT 1", 0, 5)
        j.end_migration(mid, success=True)

        summary = j.get_migration_performance_summary(mid)
        assert summary["version"] is None

    def test_summary_object_type_with_value_attribute(self):
        """object_type that has a .value attribute (enum-like) is converted."""
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid)

        enum_type = MagicMock()
        enum_type.value = "VIEW"

        j.record_statement_complete("CREATE VIEW v AS SELECT 1", 0, 10)
        j.record_object_changes(
            "CREATE VIEW v AS SELECT 1",
            0,
            [{"object_type": enum_type, "object_name": "v", "schema": ""}],
        )
        j.end_migration(mid, success=True)

        summary = j.get_migration_performance_summary(mid)
        op = summary["object_operations"][0]
        assert op["object_type"] == "VIEW"

    def test_performance_summary_attaches_object_fields_to_statements(self):
        j = MigrationJournal()
        mid = "V1__init.sql"
        j.start_migration(mid, details={"version": "1"})
        j.record_statement_complete("CREATE TABLE users (id INT)", 0, 50)
        j.record_object_changes(
            "CREATE TABLE users (id INT)",
            0,
            [{"object_type": "TABLE", "object_name": "users", "schema": "public"}],
        )
        j.end_migration(mid, success=True)

        stmt = j.get_migration_performance_summary(mid)["statements"][0]
        assert stmt["operation"] == "CREATE"
        assert stmt["object_type"] == "TABLE"
        assert stmt["object_name"] == "users"

    def test_select_statement_classified_as_query(self):
        j = MigrationJournal()
        mid = "R__test.sql"
        j.start_migration(mid)
        j.record_statement_complete(
            "SELECT object_type, object_name FROM all_objects WHERE owner = 'X'", 0, 8
        )
        j.end_migration(mid, success=True)

        stmt = j.get_migration_performance_summary(mid)["statements"][0]
        assert stmt["operation"] == "SELECT"
        assert stmt["object_type"] == "QUERY"
        assert stmt["object_name"] == "all_objects"

    def test_select_without_from_has_empty_object_name(self):
        j = MigrationJournal()
        mid = "R__ping.sql"
        j.start_migration(mid)
        j.record_statement_complete("SELECT 1", 0, 2)
        j.end_migration(mid, success=True)

        stmt = j.get_migration_performance_summary(mid)["statements"][0]
        assert stmt["operation"] == "SELECT"
        assert stmt["object_type"] == "QUERY"
        assert stmt["object_name"] == ""

    def test_repeatable_version_stays_none_in_summary(self):
        j = MigrationJournal()
        mid = "R__test.sql"
        j.start_migration(mid)
        j.record_statement_complete("SELECT 1 FROM dual", 0, 3)
        j.end_migration(mid, success=True)

        summary = j.get_migration_performance_summary(mid)
        assert summary["version"] is None
