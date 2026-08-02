"""Tests for dialect-specific LIMIT clause via BaseHistoryManager.get_row_limit_clause().

JdbcProvider no longer hosts ``get_row_limit_clause``; the canonical home is
``BaseHistoryManager``. These tests exercise the BaseHistoryManager dispatch and
its Oracle-style override.
"""

from unittest.mock import MagicMock

from db.plugins.base_history_manager import BaseHistoryManager

# ===========================================================================
# Provider-level get_row_limit_clause removed in X-11 (dead code at provider
# level; canonical home is BaseHistoryManager.get_row_limit_clause, exercised
# by the BaseHistoryManagerRowLimitClause tests below).
# ===========================================================================


# ===========================================================================
# BaseHistoryManager tests
# ===========================================================================


class TestBaseHistoryManagerRowLimitClause:

    def test_base_history_manager_row_limit_clause(self):
        """BaseHistoryManager default returns LIMIT n syntax."""
        manager = MagicMock(spec=BaseHistoryManager)
        # Call the real method on the mock
        result = BaseHistoryManager.get_row_limit_clause(manager, 1)
        assert result == "LIMIT 1"

    def test_oracle_history_manager_row_limit_clause(self):
        """OracleHistoryManager returns FETCH FIRST syntax."""
        from db.plugins.oracle.oracle.history_manager import OracleHistoryManager

        manager = MagicMock(spec=OracleHistoryManager)
        result = OracleHistoryManager.get_row_limit_clause(manager, 1)
        assert result == "FETCH FIRST 1 ROWS ONLY"


# ---------------------------------------------------------------------------
# Concrete BaseHistoryManager subclasses for SQL generation tests
# ---------------------------------------------------------------------------


class ConcreteHistoryManager(BaseHistoryManager):
    """Minimal concrete BaseHistoryManager for testing get_current_version SQL."""

    def create_migration_history_table_if_not_exists(
        self, connection, schema, create_schema=False, table_name="dblift_schema_history"
    ):
        pass

    def record_migration(self, connection, schema, migration_info, table_name=None):
        pass

    def get_applied_migrations(self, connection, schema, table_name=None):
        return []

    def create_history_table(self, schema, table_name):
        return ""


class OracleLikeHistoryManager(ConcreteHistoryManager):
    """History manager that overrides get_row_limit_clause with Oracle syntax."""

    def get_row_limit_clause(self, n: int = 1) -> str:
        return f"FETCH FIRST {n} ROWS ONLY"


def _make_history_manager(cls=ConcreteHistoryManager):
    """Create a history manager with a mocked query_executor."""
    query_executor = MagicMock()
    query_executor.table_exists.return_value = True
    query_executor.get_schema_qualified_name.return_value = "myschema.dblift_schema_history"
    return cls(
        query_executor=query_executor,
        schema_operations=MagicMock(),
        config=MagicMock(),
    )


# ===========================================================================
# get_current_version SQL generation tests
# ===========================================================================


class TestGetCurrentVersionDialect:

    def test_get_current_version_uses_limit_on_default(self):
        """Default BaseHistoryManager generates LIMIT 1 in get_current_version SQL."""
        manager = _make_history_manager()
        captured_queries = []

        def capture_query(connection, sql):
            captured_queries.append(sql)
            return [{"version": "1.0.0"}]

        manager.query_executor.execute_query = capture_query
        manager.get_current_version(connection=MagicMock(), schema="myschema")

        assert len(captured_queries) == 1
        sql = captured_queries[0]
        assert "LIMIT 1" in sql
        assert "FETCH FIRST" not in sql

    def test_get_current_version_uses_fetch_first_on_oracle(self):
        """Oracle-like history manager generates FETCH FIRST 1 ROWS ONLY in get_current_version SQL."""
        manager = _make_history_manager(cls=OracleLikeHistoryManager)
        captured_queries = []

        def capture_query(connection, sql):
            captured_queries.append(sql)
            return [{"version": "1.0.0"}]

        manager.query_executor.execute_query = capture_query
        manager.get_current_version(connection=MagicMock(), schema="myschema")

        assert len(captured_queries) == 1
        sql = captured_queries[0]
        assert "FETCH FIRST 1 ROWS ONLY" in sql
        assert "LIMIT 1" not in sql
