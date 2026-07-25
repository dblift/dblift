"""BUG-03 regression: Oracle repair uses uppercase history-table identifier.

Before ADR-0015, ``repair``'s failed-migration delete path built its
SQL as ``"DBLIFT_TEST"."dblift_schema_history"`` — ANSI-quoted
lowercase. Oracle stores the table as unquoted ``DBLIFT_SCHEMA_HISTORY``
(folded uppercase) so the quoted lowercase reference resolves to a
literally-named table that does not exist → ORA-00942.

This test pins the fix end to end: the command hands the *normalized*
table name to the history manager, and the history manager — which now
owns the DELETE — qualifies it with that name.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.logger.results import RepairResult
from core.migration.commands.repair_command import RepairCommand
from db.plugins.base_history_manager import BaseHistoryManager


class _OracleQueryExecutorStub:
    """Mirrors the part of the real Oracle query executor the DELETE path touches."""

    dialect_name = "oracle"

    def __init__(self):
        self.statements: list[tuple[str, list]] = []

    def get_schema_qualified_name(self, schema: str, table: str) -> str:
        # Real base-provider quoting: ANSI double-quotes both halves.
        # This is where the lowercase bug surfaced — quoted lowercase
        # is a LITERAL lowercase identifier to Oracle.
        return f'"{schema}"."{table}"'

    def execute_statement(self, connection, sql, params=None):
        self.statements.append((sql, params))
        return 1


class _OracleHistoryManager(BaseHistoryManager):
    """Concrete subclass — only the inherited delete path is exercised."""

    normalized_history_table = "DBLIFT_SCHEMA_HISTORY"

    def create_migration_history_table_if_not_exists(self, *args, **kwargs):
        raise NotImplementedError

    def record_migration(self, *args, **kwargs):
        raise NotImplementedError

    def get_applied_migrations(self, *args, **kwargs):
        raise NotImplementedError

    def create_history_table(self, *args, **kwargs):
        raise NotImplementedError


class _OracleProviderStub:
    def __init__(self):
        self.connection = object()

    def get_normalized_object_name(self, name: str) -> str:
        return name.upper()

    def get_schema_qualified_name(self, schema: str, table: str) -> str:
        return f'"{schema}"."{table}"'

    def _ensure_connection(self):
        return None

    def supports_transactions(self) -> bool:
        return True


def _make_repair_command() -> tuple[RepairCommand, _OracleQueryExecutorStub]:
    """Bypass BaseCommand.__init__; we only exercise _delete_failed_migration_entry."""
    cmd = RepairCommand.__new__(RepairCommand)
    cmd.log = MagicMock()
    cmd.config = SimpleNamespace(database=SimpleNamespace(schema="DBLIFT_TEST", type="oracle"))
    cmd.provider = _OracleProviderStub()

    query_executor = _OracleQueryExecutorStub()
    cmd.history_manager = _OracleHistoryManager(query_executor, None, None)
    return cmd, query_executor


@pytest.mark.unit
class TestRepairUsesNormalizedHistoryTableForOracle:
    def test_delete_sql_targets_uppercase_table(self):
        """The DELETE must reference the upper-cased form, not the lowercase one."""
        cmd, query_executor = _make_repair_command()

        repair = {
            "script": "V1__create_users.sql",
            "version": "1",
            "original_type": None,
        }

        cmd._delete_failed_migration_entry(repair, RepairResult())

        assert query_executor.statements, "expected a DELETE statement to be executed"
        delete_sql, params = query_executor.statements[0]
        assert (
            '"DBLIFT_TEST"."DBLIFT_SCHEMA_HISTORY"' in delete_sql
        ), f"DELETE must target the uppercase table on Oracle; got: {delete_sql!r}"
        # And definitely not the lowercase form that ORA-00942's on.
        assert '"dblift_schema_history"' not in delete_sql
        assert params == ["V1__create_users.sql"]

    def test_delete_uses_oracle_false_literal(self):
        """Oracle stores ``success`` as NUMBER(1): the predicate must read ``0``."""
        cmd, query_executor = _make_repair_command()

        cmd._delete_failed_migration_entry(
            {"script": "V1__create_users.sql", "version": "1", "original_type": None},
            RepairResult(),
        )

        delete_sql, _params = query_executor.statements[0]
        assert "success = 0" in delete_sql
        assert "FALSE" not in delete_sql.upper().replace("V1__CREATE_USERS.SQL", "")
