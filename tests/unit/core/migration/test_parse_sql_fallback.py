"""Migration script splitting fails closed when the dialect scanner fails."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from tests.unit._migration_factory import make_migration


@pytest.mark.unit
class TestParseSqlFallback:
    """No secondary semicolon splitter may guess execution units."""

    def _patch_sql_analyzer(self):
        """Return a patch context manager for SqlAnalyzer (inline import)."""
        import dblift.core.migration.sql.sql_analyzer as analyzer_module

        return patch.object(analyzer_module, "SqlAnalyzer")

    def test_parse_sql_refuses_when_analyzer_fails(self):
        """A scanner failure does not return guessed statements."""
        config = MagicMock()
        config.database.type = "postgresql"
        migration = make_migration(
            script_name="V1__test.sql",
            content="SELECT 1; SELECT 2; SELECT 3;",
            config=config,
        )
        with self._patch_sql_analyzer() as mock_analyzer_cls:
            mock_analyzer_cls.return_value.split_statements.side_effect = Exception("parse error")
            with pytest.raises(UnsafeStatementSplitError, match="parse error"):
                migration.parse_sql_statements()

    def test_parse_sql_does_not_reinstantiate_analyzer_after_failure(self):
        """A failure is returned without a second analyzer attempt."""
        config = MagicMock()
        config.database.type = "postgresql"
        migration = make_migration(
            script_name="V1__test.sql",
            content="INSERT INTO t VALUES (1); UPDATE t SET x=2;",
            config=config,
        )
        with self._patch_sql_analyzer() as mock_analyzer_cls:
            mock_analyzer_cls.return_value.split_statements.side_effect = Exception("parse error")
            with pytest.raises(UnsafeStatementSplitError, match="parse error"):
                migration.parse_sql_statements()

            # SqlAnalyzer is instantiated only for the authoritative attempt.
            assert mock_analyzer_cls.call_count == 1
