"""Table Partition SQL Model."""

from typing import Any, Dict, List, Optional

from dblift.core.sql_model.base import SqlObject, SqlObjectType


class Partition(SqlObject):
    """Represents a table partition."""

    def __init__(
        self,
        name: str,
        table: str,
        partition_method: str,
        partition_expression: Optional[str] = None,
        partition_description: Optional[str] = None,
        subpartitions: Optional[List["Partition"]] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
        **kwargs: Any,
    ):
        """Initialize a partition.

        Args:
            name: Partition name
            table: Table name this partition belongs to
            partition_method: Partition method (RANGE, LIST, HASH, KEY)
            partition_expression: Expression used for partitioning
            partition_description: Partition boundary description (VALUES LESS THAN, VALUES IN, etc.)
            subpartitions: List of subpartitions (for composite partitioning)
            schema: Schema name (optional)
            dialect: SQL dialect
            **kwargs: Additional dialect-specific metadata
        """
        super().__init__(name, SqlObjectType.PARTITION, schema, dialect)
        self.table = table
        self.partition_method = partition_method.upper()  # RANGE, LIST, HASH, KEY
        self.partition_expression = partition_expression
        self.partition_description = partition_description
        self.subpartitions = subpartitions or []

        # Store additional metadata
        self.metadata = kwargs

    @property
    def qualified_table_name(self) -> str:
        """Get fully qualified table name.

        Returns:
            Qualified table name (schema.table)
        """
        if self.schema:
            return f"{self.schema}.{self.table}"
        return self.table

    @property
    def create_statement(self) -> str:
        """Generate partition definition (part of ALTER TABLE or CREATE TABLE).

        Note: Partitions are typically not created standalone,
        but as part of CREATE TABLE or ALTER TABLE statements.

        Returns:
            Partition definition clause
        """
        stmt = f"PARTITION {self.format_identifier(self.name)}"

        # Add partition description (VALUES clause)
        if self.partition_description:
            stmt += f" {self.partition_description}"

        # Add subpartitions if any
        if self.subpartitions:
            sub_defs = []
            for sub in self.subpartitions:
                sub_def = f"SUBPARTITION {self.format_identifier(sub.name)}"
                if sub.partition_description:
                    sub_def += f" {sub.partition_description}"
                sub_defs.append(sub_def)

            if sub_defs:
                stmt += f" ({', '.join(sub_defs)})"

        return stmt

    def __str__(self) -> str:
        """Return string representation of the partition."""
        method_desc = f"{self.partition_method}"
        if self.partition_expression:
            method_desc += f"({self.partition_expression})"

        result = f"Partition {self.name} of {self.qualified_table_name} ({method_desc})"

        if self.subpartitions:
            result += f" with {len(self.subpartitions)} subpartitions"

        return result

    def __eq__(self, other: Any) -> bool:
        """Check if two partitions are equal."""
        if not isinstance(other, Partition):
            return False
        return (
            super().__eq__(other)
            and self.table == other.table
            and self.partition_method == other.partition_method
            and self.partition_expression == other.partition_expression
            and self.partition_description == other.partition_description
            and self.subpartitions == other.subpartitions
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Partition":
        """Create partition from dictionary representation.

        Args:
            data: Dictionary with partition attributes

        Returns:
            Partition object
        """
        # Recursively create subpartitions
        subpartitions = None
        if data.get("subpartitions"):
            subpartitions = [cls.from_dict(sub) for sub in data["subpartitions"]]

        # Extract known fields
        known_fields = {
            "name",
            "table",
            "schema",
            "partition_method",
            "partition_expression",
            "partition_description",
            "subpartitions",
            "object_type",
            "dialect",
        }

        # Additional metadata
        metadata = {k: v for k, v in data.items() if k not in known_fields}

        return cls(
            name=data["name"],
            table=data["table"],
            partition_method=data["partition_method"],
            partition_expression=data.get("partition_expression"),
            partition_description=data.get("partition_description"),
            subpartitions=subpartitions,
            schema=data.get("schema"),
            dialect=data.get("dialect"),
            **metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert partition to dictionary representation.

        Returns:
            Dictionary with partition attributes
        """
        result: Dict[str, Any] = {
            "name": self.name,
            "table": self.table,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "partition_method": self.partition_method,
            "partition_expression": self.partition_expression,
            "partition_description": self.partition_description,
        }

        # Add subpartitions
        if self.subpartitions:
            result["subpartitions"] = [sub.to_dict() for sub in self.subpartitions]

        # Add metadata
        result.update(self.metadata)

        return result
