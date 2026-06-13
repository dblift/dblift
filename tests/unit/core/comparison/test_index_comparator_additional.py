"""Additional tests for IndexComparator.

This module tests additional scenarios for IndexComparator to improve coverage.
"""

import pytest

from core.comparison.index_comparator import IndexComparator
from core.sql_model.index import Index


@pytest.mark.unit
class TestIndexComparatorAdditional:
    """Additional tests for IndexComparator."""

    def setup_method(self):
        """Set up test fixtures."""
        self.comparator = IndexComparator()

    def test_compare_indexes_uniqueness_changed(self):
        """Test detecting uniqueness change."""
        expected = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            unique=False,
            dialect="postgresql",
        )

        actual = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            unique=True,
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected, actual, "postgresql")

        assert diff is not None
        assert diff.uniqueness_changed == (False, True)

    def test_compare_indexes_type_changed(self):
        """Test detecting index type change."""
        expected = Index(
            name="idx_text",
            table_name="users",
            columns=["description"],
            type="BTREE",
            dialect="postgresql",
        )

        actual = Index(
            name="idx_text",
            table_name="users",
            columns=["description"],
            type="HASH",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected, actual, "postgresql")

        assert diff is not None
        assert diff.type_changed is not None

    def test_compare_indexes_sqlserver_type_normalization(self):
        """Test SQL Server index type normalization."""
        expected = Index(
            name="idx_users", table_name="users", columns=["id"], type="BTREE", dialect="sqlserver"
        )

        actual = Index(
            name="idx_users",
            table_name="users",
            columns=["id"],
            type="NONCLUSTERED",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_indexes(expected, actual, "sqlserver")

        # BTREE should normalize to NONCLUSTERED, so should match
        assert diff is None or diff.type_changed is None

    def test_compare_indexes_sqlserver_clustered(self):
        """Test SQL Server CLUSTERED index type."""
        expected = Index(
            name="idx_users",
            table_name="users",
            columns=["id"],
            type="CLUSTERED",
            dialect="sqlserver",
        )

        actual = Index(
            name="idx_users",
            table_name="users",
            columns=["id"],
            type="CLUSTERED",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_indexes(expected, actual, "sqlserver")

        assert diff is None or not diff.has_diffs

    def test_compare_indexes_oracle_type_normalization(self):
        """Test Oracle index type normalization."""
        expected = Index(
            name="idx_users", table_name="users", columns=["id"], type="BTREE", dialect="oracle"
        )

        actual = Index(
            name="idx_users", table_name="users", columns=["id"], type="NORMAL", dialect="oracle"
        )

        diff = self.comparator.compare_indexes(expected, actual, "oracle")

        # BTREE should normalize to NORMAL, so should match
        assert diff is None or diff.type_changed is None

    def test_compare_indexes_db2_type_normalization(self):
        """Test DB2 index type normalization."""
        expected = Index(
            name="idx_users", table_name="users", columns=["id"], type="BTREE", dialect="db2"
        )

        actual = Index(
            name="idx_users", table_name="users", columns=["id"], type="REGULAR", dialect="db2"
        )

        diff = self.comparator.compare_indexes(expected, actual, "db2")

        # BTREE should normalize to REGULAR, so should match
        assert diff is None or diff.type_changed is None

    def test_compare_indexes_mysql_online_changed(self):
        """Test detecting MySQL ONLINE/OFFLINE change."""
        expected = Index(
            name="idx_email", table_name="users", columns=["email"], online=True, dialect="mysql"
        )

        actual = Index(
            name="idx_email", table_name="users", columns=["email"], online=False, dialect="mysql"
        )

        diff = self.comparator.compare_indexes(expected, actual, "mysql")

        assert diff is not None
        assert diff.online_changed == (True, False)

    def test_compare_indexes_mysql_online_none_ignored(self):
        """Test that None values for online are ignored."""
        expected = Index(
            name="idx_email", table_name="users", columns=["email"], online=None, dialect="mysql"
        )

        actual = Index(
            name="idx_email", table_name="users", columns=["email"], online=True, dialect="mysql"
        )

        diff = self.comparator.compare_indexes(expected, actual, "mysql")

        # Should not detect difference when one is None
        assert diff is None or diff.online_changed is None

    def test_compare_indexes_postgresql_concurrently_changed(self):
        """Test detecting PostgreSQL CONCURRENTLY change."""
        expected = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            concurrently=False,
            dialect="postgresql",
        )

        actual = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            concurrently=True,
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected, actual, "postgresql")

        assert diff is not None
        assert diff.concurrently_changed == (False, True)

    def test_compare_indexes_oracle_tablespace_changed(self):
        """Test detecting Oracle tablespace change."""
        expected = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            tablespace="USERS",
            dialect="oracle",
        )

        actual = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            tablespace="DATA",
            dialect="oracle",
        )

        diff = self.comparator.compare_indexes(expected, actual, "oracle")

        assert diff is not None
        assert diff.tablespace_changed is not None

    def test_compare_indexes_oracle_tablespace_to_none(self):
        """Test detecting Oracle tablespace change to None."""
        expected = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            tablespace="USERS",
            dialect="oracle",
        )

        actual = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            tablespace=None,
            dialect="oracle",
        )

        diff = self.comparator.compare_indexes(expected, actual, "oracle")

        assert diff is not None
        assert diff.tablespace_changed is not None

    def test_compare_indexes_sqlserver_include_columns_changed(self):
        """Test detecting SQL Server INCLUDE columns change."""
        expected = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            include_columns=["name"],
            dialect="sqlserver",
        )

        actual = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            include_columns=["name", "age"],
            dialect="sqlserver",
        )

        diff = self.comparator.compare_indexes(expected, actual, "sqlserver")

        assert diff is not None
        assert diff.include_columns_changed is not None

    def test_compare_indexes_identical_returns_none(self):
        """Test that identical indexes return None."""
        expected = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            unique=False,
            dialect="postgresql",
        )

        actual = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            unique=False,
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected, actual, "postgresql")

        assert diff is None

    def test_compare_indexes_no_name_uses_actual_name(self):
        """Test comparing indexes when expected has no name."""
        expected = Index(name="", table_name="users", columns=["email"], dialect="postgresql")

        actual = Index(
            name="idx_email", table_name="users", columns=["email"], dialect="postgresql"
        )

        diff = self.comparator.compare_indexes(expected, actual, "postgresql")

        # Should use actual.name when expected.name is empty
        assert diff is None or diff.index_name == "idx_email"
