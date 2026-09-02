"""Unit tests for parse_sql_statements fallback (BUG-01, Story 13-8).

Validates that when SqlAnalyzer.split_statements raises an exception,
the fallback uses a simple semicolon-based parser instead of re-instantiating SqlAnalyzer.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dblift.core.migration.migration import Migration


@pytest.mark.unit
class TestParseSqlFallback:
    """Tests for BUG-01: parse_sql_statements fallback must differ from primary."""

    def _patch_sql_analyzer(self):
        """Return a patch context manager for SqlAnalyzer (inline import)."""
        import dblift.core.migration.sql.sql_analyzer as analyzer_module

        return patch.object(analyzer_module, "SqlAnalyzer")

    def test_parse_sql_fallback_called_when_analyzer_fails(self):
        """AC#3 — When SqlAnalyzer.split_statements raises, fallback returns statements."""
        config = MagicMock()
        config.database.type = "postgresql"
        migration = Migration(
            script_name="V1__test.sql",
            content="SELECT 1; SELECT 2; SELECT 3;",
            config=config,
        )
        with self._patch_sql_analyzer() as mock_analyzer_cls:
            mock_analyzer_cls.return_value.split_statements.side_effect = Exception("parse error")
            stmts = migration.parse_sql_statements()

        assert len(stmts) == 3
        assert stmts[0] == "SELECT 1"
        assert stmts[1] == "SELECT 2"
        assert stmts[2] == "SELECT 3"

    def test_parse_sql_fallback_uses_different_strategy(self):
        """AC#3 — Fallback does not re-instantiate SqlAnalyzer."""
        config = MagicMock()
        config.database.type = "postgresql"
        migration = Migration(
            script_name="V1__test.sql",
            content="INSERT INTO t VALUES (1); UPDATE t SET x=2;",
            config=config,
        )
        with self._patch_sql_analyzer() as mock_analyzer_cls:
            mock_analyzer_cls.return_value.split_statements.side_effect = Exception("parse error")
            migration.parse_sql_statements()

            # SqlAnalyzer should be instantiated only ONCE (the primary attempt),
            # not a second time in the fallback
            assert mock_analyzer_cls.call_count == 1
