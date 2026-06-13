"""Unit tests for SQL Model classes."""

from unittest.mock import Mock, patch

import pytest

from core.sql_model.base import (
    ConstraintType,
    ParseResult,
    SqlColumn,
    SqlConstraint,
    SqlObject,
    SqlObjectType,
    SqlStatement,
    SqlStatementType,
)
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.table import Table
from core.sql_model.table_options import OracleStorageOptions, PostgresTableOptions, TableOptions
from core.sql_model.view import View

pytestmark = [pytest.mark.unit]


class TestSqlObject:
    """Test base SqlObject functionality."""

    def test_sql_object_creation(self):
        """Test basic SQL object creation."""
        obj = SqlObject("test_object", SqlObjectType.TABLE, "TEST_SCHEMA")

        assert obj.name == "test_object"
        assert obj.schema == "TEST_SCHEMA"
        assert obj.object_type == SqlObjectType.TABLE

    def test_sql_object_without_schema(self):
        """Test SQL object creation without schema."""
        obj = SqlObject("test_object", SqlObjectType.TABLE)

        assert obj.name == "test_object"
        assert obj.schema is None

    def test_sql_object_equality(self):
        """Test SQL object equality comparison."""
        obj1 = SqlObject("test_object", SqlObjectType.TABLE, "SCHEMA1")
        obj2 = SqlObject("test_object", SqlObjectType.TABLE, "SCHEMA1")
        obj3 = SqlObject("test_object", SqlObjectType.TABLE, "SCHEMA2")
        obj4 = SqlObject("other_object", SqlObjectType.TABLE, "SCHEMA1")

        assert obj1 == obj2
        assert obj1 != obj3
        assert obj1 != obj4

    def test_sql_object_str_representation(self):
        """Test SQL object string representation."""
        obj = SqlObject("test_table", SqlObjectType.TABLE, "TEST_SCHEMA")
        str_repr = str(obj)

        assert "test_table" in str_repr
        assert "TEST_SCHEMA" in str_repr

    def test_sql_object_hash(self):
        """Test SQL object hash functionality."""
        obj1 = SqlObject("test_object", SqlObjectType.TABLE, "SCHEMA1")
        obj2 = SqlObject("test_object", SqlObjectType.TABLE, "SCHEMA1")

        assert hash(obj1) == hash(obj2)

        # Test in set/dict
        obj_set = {obj1, obj2}
        assert len(obj_set) == 1

    def test_format_identifier(self):
        """Test identifier formatting for different dialects."""
        obj = SqlObject("test_object", SqlObjectType.TABLE)

        # Test different dialects
        obj.dialect = "postgresql"
        assert obj.format_identifier("column_name") == '"column_name"'

        obj.dialect = "mysql"
        assert obj.format_identifier("column_name") == "`column_name`"

        obj.dialect = "sqlserver"
        assert obj.format_identifier("column_name") == "[column_name]"

    def test_property_explicit_marking(self):
        """Test marking properties as explicit."""
        obj = SqlObject("test_object", SqlObjectType.TABLE)

        assert not obj.is_property_explicit("test_property")

        obj.mark_property_explicit("test_property")
        assert obj.is_property_explicit("test_property")

    def test_sql_object_schema_handling(self):
        """Test SQL object creation and schema handling."""
        # Test with schema
        obj = SqlObject("test_object", SqlObjectType.TABLE, schema="TEST_SCHEMA")
        assert obj.name == "test_object"
        assert obj.schema == "TEST_SCHEMA"
        assert obj.object_type == SqlObjectType.TABLE

        # Test without schema
        obj = SqlObject("test_object", SqlObjectType.VIEW)
        assert obj.name == "test_object"
        assert obj.schema is None
        assert obj.object_type == SqlObjectType.VIEW


class TestSqlColumn:
    """Test SqlColumn functionality."""

    def test_column_creation(self):
        """Test column creation."""
        column = SqlColumn("user_id", "INT", is_nullable=False, is_primary_key=True)

        assert column.name == "user_id"
        assert column.data_type == "INT"
        assert column.nullable is False
        assert column.is_primary_key is True
        assert column.default_value is None

    def test_column_with_default(self):
        """Test column creation with default value."""
        column = SqlColumn("created_date", "DATETIME", default_value="GETDATE()")

        assert column.name == "created_date"
        assert column.data_type == "DATETIME"
        assert column.default_value == "GETDATE()"
        assert column.nullable is True  # Default

    def test_column_equality(self):
        """Test column equality."""
        col1 = SqlColumn("id", "INT", is_nullable=False)
        col2 = SqlColumn("id", "INT", is_nullable=False)
        col3 = SqlColumn("id", "VARCHAR(10)", is_nullable=False)

        assert col1 == col2
        assert col1 != col3

    def test_column_constraints(self):
        """Test column with constraints."""
        constraint = SqlConstraint(ConstraintType.UNIQUE, "uk_email", ["email"])
        column = SqlColumn("email", "VARCHAR(255)", constraints=[constraint])

        assert len(column.constraints) == 1
        assert column.constraints[0] == constraint

    def test_column_with_collation(self):
        """Test column creation with collation."""
        column = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_unicode_ci")

        assert column.name == "name"
        assert column.collation == "utf8mb4_unicode_ci"

    def test_column_collation_equality(self):
        """Test column equality with collation."""
        col1 = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_unicode_ci")
        col2 = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_unicode_ci")
        col3 = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_general_ci")

        assert col1 == col2
        assert col1 != col3

    def test_column_collation_hash(self):
        """Test column hash includes collation."""
        col1 = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_unicode_ci")
        col2 = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_unicode_ci")
        col3 = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_general_ci")

        # Equal columns should have the same hash
        assert hash(col1) == hash(col2)

        # Columns with different collations should have different hashes
        assert hash(col1) != hash(col3)

        # Verify columns can be used correctly in sets (relies on hash)
        column_set = {col1, col2, col3}
        assert len(column_set) == 2  # col1 and col2 are equal, col3 is different

    def test_column_collation_serialization(self):
        """Test column collation in to_dict and from_dict."""
        column = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_unicode_ci")
        data = column.to_dict()

        assert data["collation"] == "utf8mb4_unicode_ci"

        restored = SqlColumn.from_dict(data)
        assert restored.collation == "utf8mb4_unicode_ci"

    def test_column_explicit_properties_serialization(self):
        """Test column explicit_properties in to_dict and from_dict."""
        column = SqlColumn("name", "VARCHAR(100)")
        # Mark some properties as explicit
        column.mark_property_explicit("is_nullable")
        column.mark_property_explicit("collation")

        data = column.to_dict()

        # Verify explicit_properties is in the serialized data
        assert "explicit_properties" in data
        assert data["explicit_properties"]["is_nullable"] is True
        assert data["explicit_properties"]["collation"] is True

        # Restore and verify explicit_properties is preserved
        restored = SqlColumn.from_dict(data)
        assert restored.is_property_explicit("is_nullable") is True
        assert restored.is_property_explicit("collation") is True
        assert restored.explicit_properties == {"is_nullable": True, "collation": True}


@pytest.mark.unit
class TestSqlConstraint:
    """Test SqlConstraint functionality."""

    def test_constraint_creation(self):
        """Test constraint creation."""
        constraint = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])

        assert constraint.name == "pk_users"
        assert constraint.constraint_type == ConstraintType.PRIMARY_KEY
        assert constraint.column_names == ["id"]

    def test_foreign_key_constraint(self):
        """Test foreign key constraint."""
        fk = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            "fk_user_orders",
            ["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )

        assert fk.name == "fk_user_orders"
        assert fk.constraint_type == ConstraintType.FOREIGN_KEY
        assert fk.column_names == ["user_id"]
        assert fk.reference_table == "users"
        assert fk.reference_columns == ["id"]

    def test_check_constraint(self):
        """Test check constraint."""
        check = SqlConstraint(
            ConstraintType.CHECK, "ck_age_positive", ["age"], check_expression="age > 0"
        )

        assert check.constraint_type == ConstraintType.CHECK
        assert check.check_expression == "age > 0"


@pytest.mark.unit
class TestSqlConstraintEqFk:
    """Tests SqlConstraint.__eq__ pour les foreign keys."""

    def test_fk_different_reference_table_not_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="users")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="orders")
        assert a != b

    def test_fk_same_reference_table_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="users")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="users")
        assert a == b

    def test_fk_reference_table_case_insensitive(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="Users")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="users")
        assert a == b

    def test_fk_different_reference_columns_not_equal(self):
        a = SqlConstraint(
            ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t", reference_columns=["a"]
        )
        b = SqlConstraint(
            ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t", reference_columns=["b"]
        )
        assert a != b

    def test_fk_reference_columns_order_independent(self):
        a = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            "fk1",
            ["id"],
            reference_table="t",
            reference_columns=["a", "b"],
        )
        b = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            "fk1",
            ["id"],
            reference_table="t",
            reference_columns=["b", "a"],
        )
        assert a == b

    def test_fk_different_on_delete_not_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], on_delete="CASCADE")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], on_delete="SET NULL")
        assert a != b

    def test_fk_on_delete_case_insensitive(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], on_delete="CASCADE")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], on_delete="cascade")
        assert a == b

    def test_fk_on_update_none_vs_value_not_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], on_update="CASCADE")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        assert a != b

    def test_fk_on_update_case_insensitive(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], on_update="CASCADE")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], on_update="cascade")
        assert a == b

    def test_fk_none_reference_table_vs_value_not_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="users")
        assert a != b

    def test_fk_reference_schema_compared(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t")
        b.reference_schema = "public"
        assert a != b

    def test_fk_reference_schema_case_insensitive(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t")
        a.reference_schema = "Public"
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t")
        b.reference_schema = "public"
        assert a == b

    def test_fk_reference_schema_none_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], reference_table="t")
        assert a == b  # Both reference_schema=None


@pytest.mark.unit
class TestSqlConstraintEqCheck:
    """Tests SqlConstraint.__eq__ pour les check constraints."""

    def test_check_different_expression_not_equal(self):
        a = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="age > 0")
        b = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="age >= 0")
        assert a != b

    def test_check_same_expression_equal(self):
        a = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="age > 0")
        b = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="age > 0")
        assert a == b

    def test_check_expression_strip_whitespace(self):
        a = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression=" age > 0 ")
        b = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="age > 0")
        assert a == b

    def test_check_none_expression_vs_value_not_equal(self):
        a = SqlConstraint(ConstraintType.CHECK, "ck1", [])
        b = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="age > 0")
        assert a != b

    def test_check_non_string_expression_no_attribute_error(self):
        """Non-string check_expression (e.g. from JDBC) must not crash __eq__/__hash__."""
        a = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression=42)
        b = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="42")
        # Both compare as "42" after str(); equal
        assert a == b
        assert hash(a) == hash(b)

    def test_none_reference_columns_no_type_error(self):
        """None reference_columns/column_names (e.g. from from_dict) must not crash __eq__/__hash__."""
        a = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk1", ["id"])
        a.reference_columns = None  # Simulate from_dict or attribute mutation
        b = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk1", ["id"])
        assert a == b
        assert hash(a) == hash(b)


@pytest.mark.unit
class TestSqlConstraintEqState:
    """Tests SqlConstraint.__eq__ pour les constraint state fields."""

    def test_is_enabled_none_vs_true_equal(self):
        """None (unspecified) equals True (default is enabled)."""
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_enabled=True)
        assert a == b
        assert hash(a) == hash(b)

    def test_is_validated_none_vs_true_equal(self):
        """None (unspecified) equals True (default is validated)."""
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_validated=True)
        assert a == b
        assert hash(a) == hash(b)

    def test_is_enabled_none_vs_false_not_equal(self):
        """None (default enabled) differs from explicit False (disabled)."""
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_enabled=False)
        assert a != b

    def test_is_validated_none_vs_false_not_equal(self):
        """None (default validated) differs from explicit False (not validated)."""
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_validated=False)
        assert a != b

    def test_is_enabled_same_value_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_enabled=True)
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_enabled=True)
        assert a == b

    def test_is_validated_same_value_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_validated=True)
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_validated=True)
        assert a == b

    def test_is_enabled_true_vs_false_not_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_enabled=True)
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_enabled=False)
        assert a != b


@pytest.mark.unit
class TestSqlConstraintHashConsistency:
    """Vérifie le contrat hash/equality : a == b => hash(a) == hash(b)."""

    def test_equal_pk_constraints_same_hash(self):
        a = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk1", ["id"])
        b = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk1", ["id"])
        assert a == b
        assert hash(a) == hash(b)

    def test_equal_fk_constraints_same_hash(self):
        a = SqlConstraint(
            ConstraintType.FOREIGN_KEY, "fk1", ["uid"], reference_table="users", on_delete="CASCADE"
        )
        b = SqlConstraint(
            ConstraintType.FOREIGN_KEY, "fk1", ["uid"], reference_table="users", on_delete="cascade"
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_equal_check_constraints_same_hash(self):
        a = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression=" age > 0 ")
        b = SqlConstraint(ConstraintType.CHECK, "ck1", [], check_expression="age > 0")
        assert a == b
        assert hash(a) == hash(b)

    def test_pk_backward_compatible(self):
        """Les PK sans champs FK continuent de comparer ==."""
        a = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])
        b = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])
        assert a == b
        assert hash(a) == hash(b)

    def test_unique_backward_compatible(self):
        """Les UNIQUE sans expression continuent de comparer ==."""
        a = SqlConstraint(ConstraintType.UNIQUE, "uq_email", ["email"])
        b = SqlConstraint(ConstraintType.UNIQUE, "uq_email", ["email"])
        assert a == b
        assert hash(a) == hash(b)

    def test_different_fk_different_hash_in_set(self):
        """Two FK with different reference_table are distinct in a set."""
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="users")
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["user_id"], reference_table="orders")
        assert a != b
        fk_set = {a, b}
        assert len(fk_set) == 2


@pytest.mark.unit
class TestSqlConstraintDeferrable:
    """Tests SqlConstraint.__eq__ et __hash__ pour les champs deferrable (diff-relevant)."""

    def test_is_deferrable_none_vs_true_not_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_deferrable=True)
        assert a != b

    def test_initially_deferred_none_vs_true_not_equal(self):
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], initially_deferred=True)
        assert a != b

    def test_deferrable_same_values_equal(self):
        a = SqlConstraint(
            ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_deferrable=True, initially_deferred=False
        )
        b = SqlConstraint(
            ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_deferrable=True, initially_deferred=False
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_is_deferrable_none_vs_false_equal(self):
        """None and False are semantically equivalent (parser vs extractor defaults)."""
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], is_deferrable=False)
        assert a == b
        assert hash(a) == hash(b)

    def test_initially_deferred_none_vs_false_equal(self):
        """None and False are semantically equivalent (parser vs extractor defaults)."""
        a = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"])
        b = SqlConstraint(ConstraintType.FOREIGN_KEY, "fk1", ["id"], initially_deferred=False)
        assert a == b
        assert hash(a) == hash(b)


class TestTable:
    """Test Table functionality."""

    def test_table_creation(self):
        """Test table creation."""
        table = Table("users", schema="PUBLIC")

        assert table.name == "users"
        assert table.schema == "PUBLIC"
        assert table.object_type == SqlObjectType.TABLE
        assert table.columns == []
        assert table.constraints == []

    def test_virtual_table_round_trips_object_type_and_raw_ddl(self):
        """SQLite virtual table metadata must survive snapshot serialization."""
        ddl = "CREATE VIRTUAL TABLE users_fts USING fts5(name)"
        table = Table.from_options(
            "users_fts",
            dialect="sqlite",
            object_type=SqlObjectType.VIRTUAL_TABLE,
            options=TableOptions(raw_ddl=ddl),
        )

        restored = Table.from_dict(table.to_dict())

        assert restored.object_type == SqlObjectType.VIRTUAL_TABLE
        assert restored.raw_ddl == ddl

    def test_table_add_column(self):
        """Test adding column to table."""
        table = Table("users", schema="PUBLIC")
        column = SqlColumn("id", "INT", is_nullable=False, is_primary_key=True)

        table.add_column(column)

        assert len(table.columns) == 1
        assert table.columns[0] == column

    def test_table_add_constraint(self):
        """Test adding constraint to table."""
        table = Table("users", schema="PUBLIC")
        constraint = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])

        table.add_constraint(constraint)

        assert len(table.constraints) == 1
        assert table.constraints[0] == constraint

    def test_table_get_column(self):
        """Test getting column from table."""
        table = Table("users", schema="PUBLIC")
        id_column = SqlColumn("id", "INT")
        name_column = SqlColumn("name", "VARCHAR(100)")

        table.add_column(id_column)
        table.add_column(name_column)

        found_column = table.get_column("name")
        assert found_column == name_column

        not_found = table.get_column("email")
        assert not_found is None

    def test_table_primary_key_operations(self):
        """Test primary key operations."""
        table = Table("users", schema="PUBLIC")
        pk_constraint = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])
        table.add_constraint(pk_constraint)

        primary_key = table.get_primary_key()
        assert primary_key == pk_constraint

    def test_table_with_storage_parameters(self):
        """Test table with storage parameters (Oracle/DB2)."""
        table = Table.from_options(
            "users",
            schema="PUBLIC",
            dialect="oracle",
            options=TableOptions(
                oracle_storage=OracleStorageOptions(
                    pctfree=10, pctused=40, initial=65536, next=65536
                )
            ),
        )

        assert table.pctfree == 10
        assert table.pctused == 40
        assert table.initial == 65536
        assert table.next == 65536

    def test_table_with_inheritance(self):
        """Test table with inheritance (PostgreSQL)."""
        table = Table.from_options(
            "child_table",
            schema="public",
            dialect="postgresql",
            options=TableOptions(
                postgres=PostgresTableOptions(inherits=["parent_table1", "parent_table2"])
            ),
        )

        assert table.inherits == ["parent_table1", "parent_table2"]

    def test_table_storage_parameters_serialization(self):
        """Test table storage parameters in to_dict and from_dict."""
        table = Table.from_options(
            "users",
            schema="PUBLIC",
            dialect="oracle",
            options=TableOptions(
                oracle_storage=OracleStorageOptions(
                    pctfree=10, pctused=40, initial=65536, next=65536
                )
            ),
        )
        data = table.to_dict()

        assert data.get("pctfree") == 10
        assert data.get("pctused") == 40
        assert data.get("initial") == 65536
        assert data.get("next") == 65536

        restored = Table.from_dict(data)
        assert restored.pctfree == 10
        assert restored.pctused == 40
        assert restored.initial == 65536
        assert restored.next == 65536

    def test_table_inheritance_serialization(self):
        """Test table inheritance in to_dict and from_dict."""
        table = Table.from_options(
            "child_table",
            schema="public",
            dialect="postgresql",
            options=TableOptions(
                postgres=PostgresTableOptions(inherits=["parent_table1", "parent_table2"])
            ),
        )
        data = table.to_dict()

        assert data.get("inherits") == ["parent_table1", "parent_table2"]

        restored = Table.from_dict(data)
        assert restored.inherits == ["parent_table1", "parent_table2"]

    def test_table_metadata_round_trips(self):
        """metadata (e.g. CosmosDB partition_key) must survive to_dict/from_dict."""
        table = Table("users", dialect="cosmosdb")
        table.metadata = {"partition_key": "/userId"}

        data = table.to_dict()
        assert data.get("metadata") == {"partition_key": "/userId"}

        restored = Table.from_dict(data)
        assert restored.metadata == {"partition_key": "/userId"}

    def test_table_metadata_empty_by_default(self):
        """metadata defaults to empty dict — from_dict with no key returns {}."""
        table = Table("orders", dialect="cosmosdb")
        data = table.to_dict()
        data.pop("metadata", None)  # simulate old snapshot without metadata key
        restored = Table.from_dict(data)
        assert restored.metadata == {}

    def test_table_foreign_key_operations(self):
        """Test foreign key operations."""
        table = Table("orders", schema="PUBLIC")
        fk_constraint = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            "fk_orders_user",
            ["user_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        table.add_constraint(fk_constraint)

        foreign_keys = table.get_foreign_keys()
        assert len(foreign_keys) == 1
        assert foreign_keys[0] == fk_constraint


class TestIndex:
    """Test Index functionality."""

    def test_index_creation(self):
        """Test index creation."""
        index = Index("idx_users_name", "users", ["name"], schema="PUBLIC")

        assert index.name == "idx_users_name"
        assert index.schema == "PUBLIC"
        assert index.table_name == "users"
        assert index.columns == ["name"]
        assert index.object_type == SqlObjectType.INDEX

    def test_composite_index(self):
        """Test composite index creation."""
        index = Index("idx_users_name_email", "users", ["name", "email"], schema="PUBLIC")

        assert len(index.columns) == 2
        assert "name" in index.columns
        assert "email" in index.columns


class TestView:
    """Test View functionality."""

    def test_view_creation(self):
        """Test view creation."""
        query = "SELECT id, name FROM users WHERE active = 1"
        view = View("active_users", "PUBLIC", query)

        assert view.name == "active_users"
        assert view.schema == "PUBLIC"
        assert view.query == query
        assert view.object_type == SqlObjectType.VIEW

    def test_materialized_view_creation(self):
        """Test materialized view creation."""
        query = "SELECT COUNT(*) as total FROM users"
        view = View("user_count", "PUBLIC", query, materialized=True)

        assert view.materialized is True
        assert view.object_type == SqlObjectType.MATERIALIZED_VIEW

    def test_view_equality(self):
        """Test view equality."""
        query = "SELECT * FROM users"
        view1 = View("test_view", "PUBLIC", query)
        view2 = View("test_view", "PUBLIC", query)
        view3 = View("test_view", "PUBLIC", "SELECT id FROM users")

        assert view1 == view2
        assert view1 != view3


class TestProcedure:
    """Test Procedure functionality."""

    def test_procedure_creation(self):
        """Test procedure creation."""
        body = "BEGIN SELECT COUNT(*) FROM users; END"
        procedure = Procedure("get_user_count", schema="PUBLIC", body=body)

        assert procedure.name == "get_user_count"
        assert procedure.schema == "PUBLIC"
        assert procedure.body == body
        assert procedure.object_type == SqlObjectType.PROCEDURE

    def test_procedure_create_statement_uses_registered_generator_when_dialect_missing(self):
        """Without dialect, DDL still routes through the default PG generator (not basic DDL)."""
        procedure = Procedure("p", body="SELECT 1")
        assert procedure.dialect is None
        sql = procedure.create_statement
        assert "CREATE OR REPLACE PROCEDURE" in sql
        assert "$$" in sql
        assert "SELECT 1" in sql


class TestSequence:
    """Test Sequence functionality."""

    def test_sequence_creation(self):
        """Test sequence creation."""
        sequence = Sequence("user_id_seq", "PUBLIC")

        assert sequence.name == "user_id_seq"
        assert sequence.schema == "PUBLIC"
        assert sequence.object_type == SqlObjectType.SEQUENCE


class TestSqlStatement:
    """Test SqlStatement functionality."""

    def test_statement_creation(self):
        """Test statement creation."""
        sql_text = "CREATE TABLE users (id INT PRIMARY KEY);"
        statement = SqlStatement(sql_text, SqlStatementType.CREATE)

        assert statement.sql_text == sql_text
        assert statement.statement_type == SqlStatementType.CREATE
        assert statement.objects == []

    def test_statement_with_objects(self):
        """Test statement with objects."""
        sql_text = "CREATE TABLE users (id INT);"
        table_obj = SqlObject("users", SqlObjectType.TABLE)
        statement = SqlStatement(sql_text, SqlStatementType.CREATE, objects=[table_obj])

        assert len(statement.objects) == 1
        assert statement.get_primary_object() == table_obj


class TestParseResult:
    """Test ParseResult functionality."""

    def test_successful_parse_result(self):
        """Test successful parse result."""
        statement = SqlStatement("CREATE TABLE test (id INT);", SqlStatementType.CREATE)
        result = ParseResult(success=True, statements=[statement])

        assert result.success is True
        assert len(result.statements) == 1
        assert bool(result) is True

    def test_failed_parse_result(self):
        """Test failed parse result."""
        result = ParseResult(success=False, errors=["Syntax error"])

        assert result.success is False
        assert len(result.errors) == 1
        assert bool(result) is False


class TestSqlModelIntegration:
    """Test integration between SQL model classes."""

    def test_table_with_full_definition(self):
        """Test table with complete definition."""
        table = Table("orders", schema="SALES")

        # Add columns
        table.add_column(SqlColumn("id", "INT", is_nullable=False, is_primary_key=True))
        table.add_column(SqlColumn("user_id", "INT", is_nullable=False))
        table.add_column(SqlColumn("total", "DECIMAL(10,2)", is_nullable=False))
        table.add_column(SqlColumn("created_date", "DATETIME", default_value="GETDATE()"))

        # Add constraints
        table.add_constraint(SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_orders", ["id"]))
        table.add_constraint(
            SqlConstraint(
                ConstraintType.FOREIGN_KEY,
                "fk_orders_user",
                ["user_id"],
                reference_table="users",
                reference_columns=["id"],
            )
        )

        # Verify structure
        assert len(table.columns) == 4
        assert len(table.constraints) == 2

    def test_sql_object_type_enum(self):
        """Test SqlObjectType enum functionality."""
        assert SqlObjectType.TABLE.value == "TABLE"
        assert SqlObjectType.VIRTUAL_TABLE.value == "VIRTUAL_TABLE"
        assert SqlObjectType.VIEW.value == "VIEW"
        assert SqlObjectType.INDEX.value == "INDEX"
        assert SqlObjectType.SEQUENCE.value == "SEQUENCE"
        assert SqlObjectType.PROCEDURE.value == "PROCEDURE"

    def test_constraint_type_enum(self):
        """Test ConstraintType enum functionality."""
        assert ConstraintType.PRIMARY_KEY.value == "PRIMARY KEY"
        assert ConstraintType.FOREIGN_KEY.value == "FOREIGN KEY"
        assert ConstraintType.UNIQUE.value == "UNIQUE"
        assert ConstraintType.CHECK.value == "CHECK"

    def test_statement_type_enum(self):
        """Test SqlStatementType enum functionality."""
        assert SqlStatementType.CREATE.value == "CREATE"
        assert SqlStatementType.ALTER.value == "ALTER"
        assert SqlStatementType.DROP.value == "DROP"
        assert SqlStatementType.INSERT.value == "INSERT"

    def test_dialect_specific_data_types(self):
        """Test dialect-specific data type handling."""
        # Test PostgreSQL types
        table = Table("test_table", schema="public")
        table.dialect = "postgresql"
        table.add_column(SqlColumn("id", "SERIAL"))
        table.add_column(SqlColumn("data", "JSONB"))
        table.add_column(SqlColumn("point", "POINT"))

        assert table.get_column("id").data_type == "SERIAL"
        assert table.get_column("data").data_type == "JSONB"
        assert table.get_column("point").data_type == "POINT"

        # Test SQL Server types
        table = Table("test_table", schema="dbo")
        table.dialect = "sqlserver"
        table.add_column(SqlColumn("id", "UNIQUEIDENTIFIER"))
        table.add_column(SqlColumn("data", "NVARCHAR(MAX)"))
        table.add_column(SqlColumn("xml_data", "XML"))

        assert table.get_column("id").data_type == "UNIQUEIDENTIFIER"
        assert table.get_column("data").data_type == "NVARCHAR(MAX)"
        assert table.get_column("xml_data").data_type == "XML"

        # Test Oracle types
        table = Table("test_table", schema="SCHEMA")
        table.dialect = "oracle"
        table.add_column(SqlColumn("id", "NUMBER(19)"))
        table.add_column(SqlColumn("data", "CLOB"))
        table.add_column(SqlColumn("raw_data", "RAW(2000)"))

        assert table.get_column("id").data_type == "NUMBER(19)"
        assert table.get_column("data").data_type == "CLOB"
        assert table.get_column("raw_data").data_type == "RAW(2000)"

    def test_dialect_specific_constraints(self):
        """Test dialect-specific constraint handling."""
        # Test PostgreSQL constraints
        table = Table("test_table", schema="public")
        table.dialect = "postgresql"
        table.add_constraint(
            SqlConstraint(
                ConstraintType.CHECK,
                "ck_price_positive",
                ["price"],
                check_expression="price > 0::numeric",
            )
        )
        table.add_constraint(
            SqlConstraint(
                ConstraintType.EXCLUDE,
                "ex_overlapping_ranges",
                ["daterange"],
                check_expression="USING gist (daterange WITH &&)",
            )
        )

        assert len(table.constraints) == 2
        assert any(c.constraint_type == ConstraintType.EXCLUDE for c in table.constraints)

        # Test SQL Server constraints
        table = Table("test_table", schema="dbo")
        table.dialect = "sqlserver"
        table.add_constraint(
            SqlConstraint(
                ConstraintType.DEFAULT,
                "df_created_date",
                ["created_date"],
                check_expression="GETDATE()",
            )
        )
        table.add_constraint(
            SqlConstraint(
                ConstraintType.CHECK,
                "ck_status",
                ["status"],
                check_expression="status IN ('Active', 'Inactive')",
            )
        )

        assert len(table.constraints) == 2
        assert any(c.constraint_type == ConstraintType.DEFAULT for c in table.constraints)

        # Test Oracle constraints
        table = Table("test_table", schema="SCHEMA")
        table.dialect = "oracle"
        table.add_constraint(
            SqlConstraint(
                ConstraintType.CHECK,
                "ck_valid_date",
                ["event_date"],
                check_expression="event_date >= TRUNC(SYSDATE)",
            )
        )
        table.add_constraint(SqlConstraint(ConstraintType.UNIQUE, "uk_code", ["code"]))

        assert len(table.constraints) == 2
        # Note: deferrable attribute was removed from SqlConstraint class

    def test_dialect_specific_indexes(self):
        """Test dialect-specific index handling."""
        # Test PostgreSQL indexes
        index = Index("idx_gin_data", "test_table", ["data"], schema="public")
        index.dialect = "postgresql"
        index.index_type = "GIN"
        index.where_clause = "data IS NOT NULL"
        index.include_columns = ["id"]

        assert index.index_type == "GIN"
        assert index.where_clause == "data IS NOT NULL"
        assert index.include_columns == ["id"]

        # Test SQL Server indexes
        index = Index("idx_include_cols", "test_table", ["name"], schema="dbo")
        index.dialect = "sqlserver"
        index.include_columns = ["created_date", "modified_date"]
        index.where_clause = "is_deleted = 0"
        index.with_options = "PAD_INDEX = ON, FILLFACTOR = 90"

        assert len(index.include_columns) == 2
        assert index.where_clause == "is_deleted = 0"
        assert "FILLFACTOR = 90" in index.with_options

        # Test Oracle indexes
        index = Index("idx_bitmap", "test_table", ["status"], schema="SCHEMA")
        index.dialect = "oracle"
        index.index_type = "BITMAP"
        index.tablespace = "IDX_TBS"
        index.parallel_degree = 4

        assert index.index_type == "BITMAP"
        assert index.tablespace == "IDX_TBS"
        assert index.parallel_degree == 4

    def test_dialect_specific_views(self):
        """Test dialect-specific view handling."""
        # Test PostgreSQL views
        view = View("active_users", "public", "SELECT * FROM users WHERE active = true")
        view.dialect = "postgresql"
        view.materialized = True
        view.with_options = "WITH (fillfactor=70)"
        view.tablespace = "mv_tbs"

        assert view.materialized is True
        assert "fillfactor=70" in view.with_options
        assert view.tablespace == "mv_tbs"

        # Test SQL Server views
        view = View("user_stats", "dbo", "SELECT * FROM users")
        view.dialect = "sqlserver"
        view.with_options = "WITH SCHEMABINDING, VIEW_METADATA"
        view.check_option = "WITH CHECK OPTION"

        assert "SCHEMABINDING" in view.with_options
        assert view.check_option == "WITH CHECK OPTION"

        # Test Oracle views
        view = View("dept_summary", "SCHEMA", "SELECT * FROM departments")
        view.dialect = "oracle"
        view.force = True
        view.with_read_only = True
        view.with_check_option = "WITH CHECK OPTION CONSTRAINT ck_dept"

        assert view.force is True
        assert view.with_read_only is True
        assert "CONSTRAINT ck_dept" in view.with_check_option

    def test_dialect_specific_sequences(self):
        """Test dialect-specific sequence handling."""
        # Test PostgreSQL sequences
        sequence = Sequence("user_id_seq", "public")
        sequence.dialect = "postgresql"
        sequence.increment = 10
        sequence.min_value = 1
        sequence.max_value = 999999
        sequence.start_with = 100
        sequence.cache = 20
        sequence.cycle = True

        assert sequence.increment == 10
        assert sequence.min_value == 1
        assert sequence.max_value == 999999
        assert sequence.start_with == 100
        assert sequence.cache == 20
        assert sequence.cycle is True

        # Test Oracle sequences
        sequence = Sequence("order_seq", "SCHEMA")
        sequence.dialect = "oracle"
        sequence.increment = 5
        sequence.start_with = 1000
        sequence.cache = 50
        sequence.order = True
        sequence.cycle = False

        assert sequence.increment == 5
        assert sequence.start_with == 1000
        assert sequence.cache == 50
        assert sequence.order is True
        assert sequence.cycle is False


class TestSqlConstraintFromDictReferenceSchema:
    """Tests for NEW-BUG-14: SqlConstraint.from_dict preserves reference_schema."""

    def test_reference_schema_round_trip(self):
        """FK with reference_schema serialized to dict then deserialized preserves the field."""
        from core.sql_model.table import Table

        constraint = SqlConstraint(
            name="fk_order_customer",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["customer_id"],
            reference_table="customers",
            reference_columns=["id"],
            dialect="postgresql",
        )
        constraint.reference_schema = "other_schema"
        table = Table(name="orders", schema="public", dialect="postgresql")
        table.constraints = [constraint]
        data = table.to_dict()
        restored = Table.from_dict(data)
        assert restored.constraints[0].reference_schema == "other_schema"


class TestTableEqComment:
    """Tests for NEW-BUG-17: Table.__eq__ includes comment field."""

    def test_tables_differ_by_comment_are_not_equal(self):
        """Two tables identical except for comment should not be equal."""
        from core.sql_model.table import Table

        t1 = Table(name="orders", schema="public", dialect="postgresql", comment="v1")
        t2 = Table(name="orders", schema="public", dialect="postgresql", comment="v2")
        assert t1 != t2


class TestTableEqOracleStorageParams:
    """Tests for NEW-BUG-23: Table.__eq__ includes Oracle storage params."""

    def test_table_eq_oracle_storage_params_differ(self):
        """Two tables with different Oracle storage params should not be equal."""
        t1 = Table.from_options(
            name="orders",
            schema="hr",
            dialect="oracle",
            options=TableOptions(
                oracle_storage=OracleStorageOptions(
                    pctfree=10, pctused=40, initial=65536, next=65536
                )
            ),
        )
        t2 = Table.from_options(
            name="orders",
            schema="hr",
            dialect="oracle",
            options=TableOptions(
                oracle_storage=OracleStorageOptions(
                    pctfree=20, pctused=50, initial=131072, next=131072
                )
            ),
        )
        assert t1 != t2

    def test_table_eq_oracle_storage_params_same(self):
        """Two tables with identical Oracle storage params should be equal."""
        t1 = Table.from_options(
            name="orders",
            schema="hr",
            dialect="oracle",
            options=TableOptions(
                oracle_storage=OracleStorageOptions(
                    pctfree=10, pctused=40, initial=65536, next=65536
                )
            ),
        )
        t2 = Table.from_options(
            name="orders",
            schema="hr",
            dialect="oracle",
            options=TableOptions(
                oracle_storage=OracleStorageOptions(
                    pctfree=10, pctused=40, initial=65536, next=65536
                )
            ),
        )
        assert t1 == t2

    def test_table_eq_export_partitions_differ(self):
        """Two tables with different export_partitions should not be equal."""
        from core.sql_model.partition import Partition

        p1 = Partition(
            name="p1", table="sales", partition_method="RANGE", partition_description="100"
        )
        p2 = Partition(
            name="p2", table="sales", partition_method="RANGE", partition_description="200"
        )
        t1 = Table(name="sales", schema="hr", dialect="oracle", export_partitions=[p1])
        t2 = Table(name="sales", schema="hr", dialect="oracle", export_partitions=[p2])
        assert t1 != t2


class TestTableCheckExprParenStripping:
    """Tests for NEW-BUG-18: generate_alter_table_check_constraints uses depth-based stripping."""

    def _make_check_table(self, expr):
        from core.sql_model.base import ConstraintType, SqlConstraint
        from core.sql_model.table import Table

        c = SqlConstraint(constraint_type=ConstraintType.CHECK, check_expression=expr)
        return Table(name="t", constraints=[c], dialect="db2")

    def test_simple_outer_parens_stripped_in_sql(self):
        """(a > 0) outer parens are stripped → CHECK (a > 0) not CHECK ((a > 0))."""
        table = self._make_check_table("(a > 0)")
        sql_list = table.generate_alter_table_check_constraints()
        assert len(sql_list) == 1
        assert "CHECK (a > 0)" in sql_list[0]
        assert "CHECK ((a > 0))" not in sql_list[0]

    def test_function_call_outer_parens_stripped(self):
        """(func(a, b) > 0) — old count()==1 would NOT strip (count=2); depth algo does."""
        table = self._make_check_table("(func(a, b) > 0)")
        sql_list = table.generate_alter_table_check_constraints()
        assert len(sql_list) == 1
        # Outer parens stripped → CHECK (func(a, b) > 0)
        assert "CHECK (func(a, b) > 0)" in sql_list[0]

    def test_separate_paren_groups_not_stripped(self):
        """(a) + (b) must NOT be stripped — depth goes negative during inner scan."""
        table = self._make_check_table("(a) + (b)")
        sql_list = table.generate_alter_table_check_constraints()
        assert len(sql_list) == 1
        # Outer parens not stripped since inner scan reveals unbalanced depth
        assert "CHECK ((a) + (b))" in sql_list[0]
