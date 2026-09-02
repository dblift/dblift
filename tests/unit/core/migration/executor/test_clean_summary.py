"""Unit tests for core.migration.clean_summary module."""

import pytest

from dblift.core.migration.clean_summary import CleanedObjectInfo, CleanExecutionSummary


@pytest.mark.unit
class TestCleanedObjectInfo:
    """Test CleanedObjectInfo dataclass."""

    def test_basic_creation(self):
        """Test basic CleanedObjectInfo creation."""
        obj = CleanedObjectInfo(
            object_type="TABLE",
            name="users",
            schema="public",
        )

        assert obj.object_type == "TABLE"
        assert obj.name == "users"
        assert obj.schema == "public"
        assert obj.details == {}

    def test_with_details(self):
        """Test CleanedObjectInfo with details."""
        details = {"column_count": "5", "row_count": "100"}
        obj = CleanedObjectInfo(
            object_type="TABLE",
            name="users",
            schema="public",
            details=details,
        )

        assert obj.details == details

    def test_immutable(self):
        """Test that CleanedObjectInfo is immutable (frozen dataclass)."""
        obj = CleanedObjectInfo(object_type="TABLE", name="users")

        with pytest.raises(Exception):  # Should raise FrozenInstanceError or similar
            obj.name = "orders"


@pytest.mark.unit
class TestCleanExecutionSummary:
    """Test CleanExecutionSummary class."""

    def test_initialization(self):
        """Test CleanExecutionSummary initialization."""
        summary = CleanExecutionSummary()

        assert summary.statements == []
        assert summary.objects == []

    def test_add_statement(self):
        """Test adding SQL statements."""
        summary = CleanExecutionSummary()
        summary.add_statement("DROP TABLE users;")
        summary.add_statement("DROP TABLE orders;")

        assert len(summary.statements) == 2
        assert "DROP TABLE users;" in summary.statements
        assert "DROP TABLE orders;" in summary.statements

    def test_add_statement_empty(self):
        """Test adding empty statement is ignored."""
        summary = CleanExecutionSummary()
        summary.add_statement("")
        summary.add_statement(None)

        assert len(summary.statements) == 0

    def test_add_object(self):
        """Test adding object metadata."""
        summary = CleanExecutionSummary()
        summary.add_object("TABLE", "users", schema="public")

        assert len(summary.objects) == 1
        obj = summary.objects[0]
        assert obj.object_type == "TABLE"
        assert obj.name == "users"
        assert obj.schema == "public"

    def test_add_object_with_details(self):
        """Test adding object with details."""
        summary = CleanExecutionSummary()
        details = {"column_count": "5"}
        summary.add_object("TABLE", "users", schema="public", details=details)

        assert len(summary.objects) == 1
        assert summary.objects[0].details == details

    def test_record_drop(self):
        """Test record_drop convenience method."""
        summary = CleanExecutionSummary()
        summary.record_drop(
            "DROP TABLE users;",
            "TABLE",
            "users",
            schema="public",
            details={"column_count": "5"},
        )

        assert len(summary.statements) == 1
        assert len(summary.objects) == 1
        assert summary.statements[0] == "DROP TABLE users;"
        assert summary.objects[0].name == "users"

    def test_extend_with_other_summary(self):
        """Test extending with another summary."""
        summary1 = CleanExecutionSummary()
        summary1.add_statement("DROP TABLE users;")
        summary1.add_object("TABLE", "users")

        summary2 = CleanExecutionSummary()
        summary2.add_statement("DROP TABLE orders;")
        summary2.add_object("TABLE", "orders")

        summary1.extend(summary2)

        assert len(summary1.statements) == 2
        assert len(summary1.objects) == 2
        assert "DROP TABLE users;" in summary1.statements
        assert "DROP TABLE orders;" in summary1.statements

    def test_extend_with_none(self):
        """Test extending with None does nothing."""
        summary = CleanExecutionSummary()
        summary.add_statement("DROP TABLE users;")

        summary.extend(None)

        assert len(summary.statements) == 1

    def test_extend_with_empty_summary(self):
        """Test extending with empty summary."""
        summary1 = CleanExecutionSummary()
        summary1.add_statement("DROP TABLE users;")

        summary2 = CleanExecutionSummary()
        summary1.extend(summary2)

        assert len(summary1.statements) == 1

    def test_multiple_operations(self):
        """Test multiple operations on summary."""
        summary = CleanExecutionSummary()

        # Add statements
        summary.add_statement("DROP TABLE users;")
        summary.add_statement("DROP VIEW user_view;")

        # Add objects
        summary.add_object("TABLE", "users")
        summary.add_object("VIEW", "user_view")

        # Record drop
        summary.record_drop("DROP INDEX idx_users;", "INDEX", "idx_users")

        assert len(summary.statements) == 3
        assert len(summary.objects) == 3
