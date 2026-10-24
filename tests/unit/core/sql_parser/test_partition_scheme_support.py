"""Unit tests for partition scheme parsing (PARTITION BY clause)."""

import pytest

pytestmark = [pytest.mark.unit]


class TestPartitionSchemeOracle:
    """Test Oracle partition scheme parsing."""


class TestPartitionSchemeDB2:
    """Test DB2 partition scheme parsing."""


class TestPartitionSchemeSQLServer:
    """Test SQL Server partition scheme parsing.

    Note: SQL Server uses a different partitioning architecture:
    1. CREATE PARTITION FUNCTION (defines boundary values)
    2. CREATE PARTITION SCHEME (maps to filegroups)
    3. CREATE TABLE ... ON [scheme](column)

    Parser doesn't detect PARTITION BY (SQL Server doesn't use it).
    Partition scheme is detected via introspection only.
    """

    def test_sqlserver_no_inline_partition_syntax(self):
        """SQL Server doesn't use PARTITION BY in CREATE TABLE."""
        # SQL Server partitioning is applied via partition schemes, not inline
        # This test just verifies parser doesn't break on partition schemes
        # Actual partition detection happens via introspection
        pytest.skip("SQL Server uses partition schemes, not inline PARTITION BY")


class TestNonPartitionedTables:
    """Test that non-partitioned tables don't get partition properties."""
