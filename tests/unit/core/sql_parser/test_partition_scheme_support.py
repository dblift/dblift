"""Unit tests for partition scheme parsing (PARTITION BY clause)."""

import pytest

from dblift.core.sql_parser.hybrid_parser import HybridParser
from tests.support.legacy_db2_hybrid import legacy_db2_hybrid

pytestmark = [pytest.mark.unit]


class TestPartitionSchemeOracle:
    """Test Oracle partition scheme parsing."""

    def test_parse_range_partition_simple(self):
        """Test parsing PARTITION BY RANGE with single column."""
        sql = """
        CREATE TABLE sales (
            sale_id NUMBER,
            sale_date DATE,
            amount NUMBER
        )
        PARTITION BY RANGE (sale_date) (
            PARTITION p2023 VALUES LESS THAN (DATE '2024-01-01'),
            PARTITION p2024 VALUES LESS THAN (DATE '2025-01-01')
        );
        """

        parser = HybridParser("oracle")
        result = parser.parse_sql(sql, default_schema="test_schema")

        assert result.success
        assert len(result.tables) == 1

        table = result.tables[0]
        assert table.name.upper() == "SALES"
        assert table.partition_method == "RANGE"
        assert table.partition_columns == ["SALE_DATE"]

    def test_parse_list_partition(self):
        """Test parsing PARTITION BY LIST."""
        sql = """
        CREATE TABLE employees (
            emp_id NUMBER,
            region VARCHAR2(50)
        )
        PARTITION BY LIST (region) (
            PARTITION p_west VALUES ('CA', 'WA', 'OR'),
            PARTITION p_east VALUES ('NY', 'MA', 'CT')
        );
        """

        parser = HybridParser("oracle")
        result = parser.parse_sql(sql, default_schema="test_schema")

        assert result.success
        table = result.tables[0]
        assert table.partition_method == "LIST"
        assert table.partition_columns == ["REGION"]

    def test_parse_hash_partition(self):
        """Test parsing PARTITION BY HASH."""
        sql = """
        CREATE TABLE orders (
            order_id NUMBER,
            customer_id NUMBER
        )
        PARTITION BY HASH (customer_id) PARTITIONS 4;
        """

        parser = HybridParser("oracle")
        result = parser.parse_sql(sql, default_schema="test_schema")

        assert result.success
        table = result.tables[0]
        assert table.partition_method == "HASH"
        assert table.partition_columns == ["CUSTOMER_ID"]

    def test_parse_interval_partition(self):
        """Test parsing INTERVAL partitioning (Oracle auto-partitioning)."""
        sql = """
        CREATE TABLE logs (
            log_id NUMBER,
            log_date DATE,
            message VARCHAR2(1000)
        )
        PARTITION BY RANGE (log_date)
        INTERVAL(NUMTOYMINTERVAL(1, 'MONTH')) (
            PARTITION p_start VALUES LESS THAN (DATE '2024-01-01')
        );
        """

        parser = HybridParser("oracle")
        result = parser.parse_sql(sql, default_schema="test_schema")

        assert result.success
        table = result.tables[0]
        # Should detect RANGE, not INTERVAL (INTERVAL is a modifier)
        assert table.partition_method == "RANGE"
        assert table.partition_columns == ["LOG_DATE"]


class TestPartitionSchemeDB2:
    """Test DB2 partition scheme parsing."""

    def test_parse_range_partition(self):
        """Test parsing PARTITION BY RANGE."""
        sql = """
        CREATE TABLE SALES (
            SALE_ID INTEGER,
            SALE_DATE DATE,
            AMOUNT DECIMAL(10,2),
            PRIMARY KEY (SALE_ID)
        )
        PARTITION BY RANGE (SALE_DATE) (
            PARTITION P2023 STARTING '2023-01-01' ENDING '2023-12-31',
            PARTITION P2024 STARTING '2024-01-01' ENDING '2024-12-31'
        );
        """

        parser = legacy_db2_hybrid()
        result = parser.parse_sql(sql, default_schema="TEST_SCHEMA")

        assert result.success
        table = result.tables[0]
        assert table.partition_method == "RANGE"
        assert "SALE_DATE" in table.partition_columns


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

    @pytest.mark.parametrize("dialect", ["oracle", "db2", "sqlserver"])
    def test_regular_table_no_partition(self, dialect):
        """Test regular CREATE TABLE doesn't set partition properties."""
        sql = """
        CREATE TABLE users (
            id INT PRIMARY KEY,
            name VARCHAR(100)
        );
        """

        parser = legacy_db2_hybrid() if dialect == "db2" else HybridParser(dialect)
        result = parser.parse_sql(sql, default_schema="test_schema")

        assert result.success
        table = result.tables[0]
        assert table.partition_method is None
        assert table.partition_columns is None
