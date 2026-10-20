"""Explicit test-only access to SQL Server's former SQL-file parser builders.

The public SQL Server parser reads statement facts. These helpers keep tests of the
older hybrid and SQLGlot builders without changing the public parser contract.
"""

from unittest.mock import patch

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks


def legacy_sqlserver_hybrid() -> HybridParser:
    with patch.object(SqlserverQuirks, "statement_facts_class", None):
        return HybridParser("sqlserver")


def legacy_sqlserver_sqlglot() -> SqlGlotParser:
    with patch.object(SqlserverQuirks, "statement_facts_class", None):
        return SqlGlotParser("sqlserver")
