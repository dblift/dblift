"""Unit tests for Partition SQL Model."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_model.partition import Partition

pytestmark = [pytest.mark.unit]


class TestPartition:
    """Tests for the Partition SQL Model class."""

    def test_partition_creation(self):
        """Test basic partition creation."""
        partition = Partition(
            name="p2024",
            table="sales",
            partition_method="RANGE",
            partition_expression="YEAR(sale_date)",
            partition_description="VALUES LESS THAN (2025)",
            schema="analytics",
        )

        assert partition.name == "p2024"
        assert partition.table == "sales"
        assert partition.partition_method == "RANGE"
        assert partition.partition_expression == "YEAR(sale_date)"
        assert partition.partition_description == "VALUES LESS THAN (2025)"
        assert partition.schema == "analytics"
        assert partition.object_type == SqlObjectType.PARTITION
        assert partition.subpartitions == []

    def test_partition_with_minimal_attributes(self):
        """Test partition creation with minimal attributes."""
        partition = Partition(
            name="p1",
            table="orders",
            partition_method="HASH",
        )

        assert partition.name == "p1"
        assert partition.table == "orders"
        assert partition.partition_method == "HASH"
        assert partition.partition_expression is None
        assert partition.subpartitions == []

    def test_partition_method_normalization(self):
        """Test partition method is uppercased."""
        partition = Partition(
            name="p1",
            table="t1",
            partition_method="range",  # lowercase
        )

        assert partition.partition_method == "RANGE"  # Should be uppercased

    def test_partition_with_subpartitions(self):
        """Test partition with subpartitions (composite partitioning)."""
        sub1 = Partition(
            name="sp1",
            table="sales",
            partition_method="HASH",
        )
        sub2 = Partition(
            name="sp2",
            table="sales",
            partition_method="HASH",
        )

        main_partition = Partition(
            name="p2024",
            table="sales",
            partition_method="RANGE",
            partition_expression="YEAR(sale_date)",
            subpartitions=[sub1, sub2],
        )

        assert len(main_partition.subpartitions) == 2
        assert main_partition.subpartitions[0].name == "sp1"
        assert main_partition.subpartitions[1].name == "sp2"

    def test_partition_qualified_table_name(self):
        """Test qualified table name property."""
        part_with_schema = Partition(
            name="p1",
            table="orders",
            partition_method="RANGE",
            schema="sales",
        )
        part_without_schema = Partition(
            name="p1",
            table="orders",
            partition_method="RANGE",
        )

        assert part_with_schema.qualified_table_name == "sales.orders"
        assert part_without_schema.qualified_table_name == "orders"

    def test_partition_create_statement_simple(self):
        """Test partition definition statement generation."""
        partition = Partition(
            name="p2024",
            table="sales",
            partition_method="RANGE",
            partition_description="VALUES LESS THAN (2025)",
        )

        stmt = partition.create_statement
        assert "PARTITION p2024" in stmt
        assert "VALUES LESS THAN (2025)" in stmt

    def test_partition_create_statement_with_subpartitions(self):
        """Test partition definition with subpartitions."""
        sub1 = Partition(
            name="sp1",
            table="sales",
            partition_method="HASH",
            partition_description="VALUES IN (1, 2, 3)",
        )
        sub2 = Partition(
            name="sp2",
            table="sales",
            partition_method="HASH",
            partition_description="VALUES IN (4, 5, 6)",
        )

        partition = Partition(
            name="p2024",
            table="sales",
            partition_method="RANGE",
            subpartitions=[sub1, sub2],
        )

        stmt = partition.create_statement
        assert "PARTITION p2024" in stmt
        assert "SUBPARTITION sp1" in stmt
        assert "SUBPARTITION sp2" in stmt
        assert "VALUES IN (1, 2, 3)" in stmt
        assert "VALUES IN (4, 5, 6)" in stmt

    def test_partition_str_representation(self):
        """Test string representation."""
        partition = Partition(
            name="p2024",
            table="sales",
            partition_method="RANGE",
            partition_expression="YEAR(sale_date)",
            schema="analytics",
        )

        str_repr = str(partition)
        assert "p2024" in str_repr
        assert "analytics.sales" in str_repr
        assert "RANGE(YEAR(sale_date))" in str_repr

    def test_partition_str_with_subpartitions(self):
        """Test string representation with subpartitions."""
        sub1 = Partition(name="sp1", table="t1", partition_method="HASH")
        sub2 = Partition(name="sp2", table="t1", partition_method="HASH")

        partition = Partition(
            name="p1",
            table="t1",
            partition_method="RANGE",
            subpartitions=[sub1, sub2],
        )

        str_repr = str(partition)
        assert "2 subpartitions" in str_repr

    def test_partition_equality(self):
        """Test partition equality comparison."""
        part1 = Partition(
            name="p1",
            table="t1",
            partition_method="RANGE",
            partition_expression="expr1",
            partition_description="desc1",
        )
        part2 = Partition(
            name="p1",
            table="t1",
            partition_method="RANGE",
            partition_expression="expr1",
            partition_description="desc1",
        )
        part3 = Partition(
            name="p1",
            table="t1",
            partition_method="LIST",  # Different
            partition_expression="expr1",
            partition_description="desc1",
        )

        assert part1 == part2
        assert part1 != part3
        assert part1 != "not a partition"

    def test_partition_to_dict(self):
        """Test conversion to dictionary."""
        partition = Partition(
            name="p2024",
            table="sales",
            partition_method="RANGE",
            partition_expression="YEAR(sale_date)",
            partition_description="VALUES LESS THAN (2025)",
            schema="analytics",
            # Additional metadata
            partition_number=1,
            high_value="2025",
        )

        part_dict = partition.to_dict()

        assert part_dict["name"] == "p2024"
        assert part_dict["table"] == "sales"
        assert part_dict["schema"] == "analytics"
        assert part_dict["object_type"] == "PARTITION"
        assert part_dict["partition_method"] == "RANGE"
        assert part_dict["partition_expression"] == "YEAR(sale_date)"
        assert part_dict["partition_description"] == "VALUES LESS THAN (2025)"
        assert part_dict["partition_number"] == 1
        assert part_dict["high_value"] == "2025"

    def test_partition_to_dict_with_subpartitions(self):
        """Test to_dict with subpartitions."""
        sub = Partition(name="sp1", table="t1", partition_method="HASH")
        partition = Partition(
            name="p1",
            table="t1",
            partition_method="RANGE",
            subpartitions=[sub],
        )

        part_dict = partition.to_dict()

        assert "subpartitions" in part_dict
        assert len(part_dict["subpartitions"]) == 1
        assert part_dict["subpartitions"][0]["name"] == "sp1"

    def test_partition_from_dict(self):
        """Test creation from dictionary."""
        part_dict = {
            "name": "p2024",
            "table": "sales",
            "partition_method": "RANGE",
            "partition_expression": "YEAR(sale_date)",
            "partition_description": "VALUES LESS THAN (2025)",
            "schema": "analytics",
            "partition_number": 1,
        }

        partition = Partition.from_dict(part_dict)

        assert partition.name == "p2024"
        assert partition.table == "sales"
        assert partition.partition_method == "RANGE"
        assert partition.partition_expression == "YEAR(sale_date)"
        assert partition.partition_description == "VALUES LESS THAN (2025)"
        assert partition.schema == "analytics"
        assert partition.metadata["partition_number"] == 1

    def test_partition_from_dict_with_subpartitions(self):
        """Test from_dict with subpartitions (recursive)."""
        part_dict = {
            "name": "p1",
            "table": "t1",
            "partition_method": "RANGE",
            "subpartitions": [
                {"name": "sp1", "table": "t1", "partition_method": "HASH"},
                {"name": "sp2", "table": "t1", "partition_method": "HASH"},
            ],
        }

        partition = Partition.from_dict(part_dict)

        assert len(partition.subpartitions) == 2
        assert partition.subpartitions[0].name == "sp1"
        assert partition.subpartitions[1].name == "sp2"

    def test_partition_round_trip(self):
        """Test to_dict/from_dict round trip."""
        original = Partition(
            name="p1",
            table="t1",
            partition_method="RANGE",
            partition_expression="expr",
            partition_description="desc",
            schema="s1",
        )

        # Round trip
        part_dict = original.to_dict()
        restored = Partition.from_dict(part_dict)

        assert original == restored

    def test_partition_additional_metadata(self):
        """Test that additional metadata is stored and retrieved."""
        partition = Partition(
            name="p1",
            table="t1",
            partition_method="RANGE",
            # Additional metadata via kwargs
            custom_field="custom_value",
            row_count=1000,
        )

        assert partition.metadata["custom_field"] == "custom_value"
        assert partition.metadata["row_count"] == 1000

        # Should be in dict
        part_dict = partition.to_dict()
        assert part_dict["custom_field"] == "custom_value"
        assert part_dict["row_count"] == 1000

    def test_partition_methods_range_list_hash_key(self):
        """Test different partition methods."""
        range_part = Partition(name="p1", table="t", partition_method="RANGE")
        list_part = Partition(name="p2", table="t", partition_method="LIST")
        hash_part = Partition(name="p3", table="t", partition_method="HASH")
        key_part = Partition(name="p4", table="t", partition_method="KEY")

        assert range_part.partition_method == "RANGE"
        assert list_part.partition_method == "LIST"
        assert hash_part.partition_method == "HASH"
        assert key_part.partition_method == "KEY"
