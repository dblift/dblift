"""Tests for BasicTableDdlGenerator — delegation and DDL output."""

import inspect
import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.sql_generator.base_generator import _schema_prefix_from_object
from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table

pytestmark = [pytest.mark.unit]


class TestTableDdlDelegation(unittest.TestCase):
    """Verify Table delegates DDL generation to BasicTableDdlGenerator."""

    def _make_simple_table(self, dialect=None) -> Table:
        col = SqlColumn("id", "INTEGER", is_nullable=False)
        return Table("users", columns=[col], dialect=dialect)

    def test_create_statement_fallback_uses_basic_generator(self):
        """When SqlGeneratorFactory raises, create_statement uses BasicTableDdlGenerator."""
        table = self._make_simple_table()
        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            side_effect=ValueError("no generator"),
        ):
            result = table.create_statement
        self.assertIn("CREATE TABLE", result)
        self.assertIn("users", result)

    def test_drop_statement_delegates_to_basic_generator(self):
        """Table.drop_statement returns same result as BasicTableDdlGenerator."""
        table = self._make_simple_table()
        gen = BasicTableDdlGenerator(table)
        expected = gen.generate_drop_statement()
        self.assertEqual(table.drop_statement, expected)

    def test_named_table_primary_key_suppresses_inline_column_primary_key(self):
        """Column PK metadata must not duplicate a named table-level PK constraint."""
        col = SqlColumn("id", "INTEGER", is_nullable=False, is_primary_key=True)
        constraint = SqlConstraint(
            constraint_type=ConstraintType.PRIMARY_KEY,
            name="pk_users",
            column_names=["id"],
        )
        table = Table("users", columns=[col], constraints=[constraint], dialect="postgresql")

        ddl = BasicTableDdlGenerator(table).generate_create_statement()

        assert ddl.count("PRIMARY KEY") == 1
        assert "CONSTRAINT" in ddl
        assert "pk_users" in ddl

    def test_generate_alter_self_referencing_fks_delegates(self):
        """Self-referencing FK method delegates to BasicTableDdlGenerator (empty when no self-ref FKs)."""
        table = self._make_simple_table()
        result = table.generate_alter_table_self_referencing_foreign_keys()
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])  # no self-referencing FK → empty list

    def test_generate_alter_self_referencing_fks_with_real_fk_returns_list(self):
        """Table with a FK produces a list result from generate_alter_table_self_referencing_foreign_keys."""
        fk = SqlConstraint(
            constraint_type=ConstraintType.FOREIGN_KEY,
            name="fk_parent",
            column_names=["parent_id"],
            reference_table="users",
            reference_columns=["id"],
        )
        table = self._make_simple_table(dialect="postgresql")
        table.add_constraint(fk)
        result = table.generate_alter_table_self_referencing_foreign_keys()
        self.assertIsInstance(result, list)

    def test_basic_generator_create_statement_simple_table(self):
        """BasicTableDdlGenerator produces valid CREATE TABLE DDL."""
        table = self._make_simple_table()
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        self.assertIn("CREATE TABLE", ddl)
        self.assertIn("users", ddl)
        self.assertIn("id", ddl)

    def test_basic_generator_drop_statement_default(self):
        """Default dialect produces DROP TABLE IF EXISTS ... CASCADE."""
        table = self._make_simple_table()
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_drop_statement()
        self.assertIn("DROP TABLE", ddl)
        self.assertIn("IF EXISTS", ddl)

    def test_basic_generator_accepts_table_in_constructor(self):
        """Constructor stores table reference."""
        table = self._make_simple_table()
        gen = BasicTableDdlGenerator(table)
        self.assertIs(gen.table, table)

    def test_basic_generator_drop_statement_mysql(self):
        """MySQL dialect produces DROP TABLE IF EXISTS without CASCADE."""
        table = self._make_simple_table(dialect="mysql")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_drop_statement()
        self.assertIn("DROP TABLE IF EXISTS", ddl)
        self.assertNotIn("CASCADE", ddl)

    def test_delegation_consistency_create_statement(self):
        """Table.create_statement fallback matches direct BasicTableDdlGenerator call."""
        table = self._make_simple_table()
        gen = BasicTableDdlGenerator(table)
        direct = gen.generate_create_statement()
        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            side_effect=ValueError("no generator"),
        ):
            via_table = table.create_statement
        self.assertEqual(direct, via_table)


class TestPostgreSQLNextvalDefault(unittest.TestCase):
    def test_postgresql_enhancement_preserves_nextval_default(self):
        from db.plugins.postgresql.quirks import PostgresqlQuirks

        column = SqlColumn(
            "id",
            "serial",
            default_value="nextval('order_seq'::regclass)",
            is_identity=True,
            dialect="postgresql",
        )

        PostgresqlQuirks().enhance_columns(None, "public", "orders", [column])

        self.assertEqual(column.data_type, "INTEGER")
        self.assertFalse(column.is_identity)
        self.assertEqual(column.default_value, "nextval('order_seq'::regclass)")

    def test_nextval_default_is_not_rendered_as_identity(self):
        table = Table(
            "orders",
            columns=[
                SqlColumn(
                    "id",
                    "INTEGER",
                    default_value="nextval('order_seq'::regclass)",
                    is_identity=True,
                    dialect="postgresql",
                )
            ],
            dialect="postgresql",
        )

        ddl = BasicTableDdlGenerator(table).generate_create_statement()

        self.assertIn("DEFAULT nextval('order_seq'::regclass)", ddl)
        self.assertNotIn("GENERATED BY DEFAULT AS IDENTITY", ddl)

    def test_explicit_nextval_default_is_schema_qualified(self):
        table = Table(
            "orders",
            schema="dblift_test",
            columns=[
                SqlColumn(
                    "id",
                    "INTEGER",
                    default_value="nextval('order_seq'::regclass)",
                    dialect="postgresql",
                )
            ],
            dialect="postgresql",
        )

        ddl = BasicTableDdlGenerator(table).generate_create_statement()

        self.assertIn("DEFAULT nextval('dblift_test.order_seq'::regclass)", ddl)

    def test_postgresql_nextval_cast_default_is_normalized(self):
        table = Table(
            "users",
            columns=[
                SqlColumn(
                    "id",
                    "INTEGER",
                    default_value="NEXTVAL(CAST('users_id_seq' AS REGCLASS))",
                    dialect="postgresql",
                )
            ],
            dialect="postgresql",
        )

        ddl = BasicTableDdlGenerator(table).generate_create_statement()

        self.assertIn("GENERATED BY DEFAULT AS IDENTITY", ddl)
        self.assertNotIn("DEFAULT nextval", ddl)
        self.assertNotIn("NEXTVAL(CAST", ddl)


class TestNoTrailingComma(unittest.TestCase):
    """Verify that generated DDL never contains trailing commas or double commas."""

    def test_column_definition_no_trailing_comma_simple(self):
        """A simple column definition has no trailing comma."""
        col = SqlColumn("id", "INTEGER", is_nullable=False)
        table = Table("t", columns=[col], dialect="postgresql")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        # Extract the definitions block between parentheses
        paren_start = ddl.index("(")
        paren_end = ddl.rindex(")")
        definitions_block = ddl[paren_start + 1 : paren_end].strip()
        self.assertFalse(
            definitions_block.endswith(","), f"Trailing comma found: {definitions_block!r}"
        )
        self.assertNotIn(",,", definitions_block)

    def test_column_definition_no_trailing_comma_with_identity(self):
        """A column with identity/default attributes has no trailing comma."""
        col = SqlColumn(
            "id",
            "INTEGER",
            is_nullable=False,
            is_identity=True,
            identity_seed=1,
            identity_increment=1,
        )
        table = Table("t", columns=[col], dialect="mysql")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        paren_start = ddl.index("(")
        paren_end = ddl.rindex(")")
        definitions_block = ddl[paren_start + 1 : paren_end].strip()
        self.assertFalse(
            definitions_block.endswith(","), f"Trailing comma found: {definitions_block!r}"
        )
        self.assertNotIn(",,", definitions_block)

    def test_column_definition_no_trailing_comma_with_collation(self):
        """A column with a collation attribute has no trailing comma."""
        col = SqlColumn("name", "VARCHAR(100)", is_nullable=True)
        col.collation = "en_US.UTF-8"
        table = Table("t", columns=[col], dialect="postgresql")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        paren_start = ddl.index("(")
        paren_end = ddl.rindex(")")
        definitions_block = ddl[paren_start + 1 : paren_end].strip()
        self.assertFalse(
            definitions_block.endswith(","), f"Trailing comma found: {definitions_block!r}"
        )
        self.assertNotIn(",,", definitions_block)
        self.assertIn("COLLATE", definitions_block)

    def test_create_table_multiple_columns_and_constraints_no_trailing_comma(self):
        """CREATE TABLE with columns + PK + FK has no trailing or double commas."""
        col_id = SqlColumn("id", "INTEGER", is_nullable=False)
        col_name = SqlColumn("name", "VARCHAR(100)", is_nullable=True)
        col_ref = SqlColumn("parent_id", "INTEGER", is_nullable=True)
        pk = SqlConstraint(
            constraint_type=ConstraintType.PRIMARY_KEY,
            name="pk_t",
            column_names=["id"],
        )
        fk = SqlConstraint(
            constraint_type=ConstraintType.FOREIGN_KEY,
            name="fk_parent",
            column_names=["parent_id"],
            reference_table="other_table",
            reference_columns=["id"],
        )
        table = Table("t", columns=[col_id, col_name, col_ref], dialect="postgresql")
        table.add_constraint(pk)
        table.add_constraint(fk)
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        paren_start = ddl.index("(")
        paren_end = ddl.rindex(")")
        definitions_block = ddl[paren_start + 1 : paren_end].strip()
        self.assertFalse(
            definitions_block.endswith(","), f"Trailing comma found: {definitions_block!r}"
        )
        self.assertNotIn(",,", definitions_block)
        # Verify all elements are present
        self.assertIn("id", definitions_block)
        self.assertIn("name", definitions_block)
        self.assertIn("parent_id", definitions_block)
        self.assertIn("PRIMARY KEY", definitions_block)
        self.assertIn("FOREIGN KEY", definitions_block)


class TestCheckConstraintParenStrippingInline(unittest.TestCase):
    """Tests AC#2/3/4 de story 15-3 : depth-based stripping dans _generate_constraint_definitions."""

    def _make_gen(self, expr, dialect=None):
        col = SqlColumn("val", "INTEGER", is_nullable=True)
        c = SqlConstraint(constraint_type=ConstraintType.CHECK, check_expression=expr)
        table = Table("t", columns=[col], constraints=[c], dialect=dialect)
        return BasicTableDdlGenerator(table)

    def test_simple_outer_parens_stripped_inline(self):
        """(a > 0) -> CHECK (a > 0) in CREATE TABLE, not CHECK ((a > 0))."""
        ddl = self._make_gen("(a > 0)").generate_create_statement()
        self.assertIn("CHECK (a > 0)", ddl)
        self.assertNotIn("CHECK ((a > 0))", ddl)

    def test_nested_function_outer_parens_stripped_inline(self):
        """(func(a, b) > 0) -- old count==1 fails; depth algo strips correctly."""
        ddl = self._make_gen("(func(a, b) > 0)").generate_create_statement()
        self.assertIn("CHECK (func(a, b) > 0)", ddl)
        self.assertNotIn("CHECK ((func(a, b) > 0))", ddl)

    def test_separate_paren_groups_not_stripped_inline(self):
        """(a) + (b) must NOT be stripped -- depth goes negative during inner scan."""
        ddl = self._make_gen("(a) + (b)").generate_create_statement()
        self.assertIn("CHECK ((a) + (b))", ddl)
        self.assertNotIn("CHECK (a) + (b)", ddl)

    def test_no_outer_parens_unchanged(self):
        """Expression without outer parens is passed through as-is."""
        ddl = self._make_gen("a > 0").generate_create_statement()
        self.assertIn("CHECK (a > 0)", ddl)
        self.assertNotIn("CHECK ((a > 0))", ddl)

    def test_adjacent_paren_groups_not_stripped(self):
        """(a)(b) — inner scan hits ) before any ( → depth goes negative → not stripped."""
        ddl = self._make_gen("(a)(b)").generate_create_statement()
        self.assertIn("CHECK ((a)(b))", ddl)
        self.assertNotIn("CHECK (a)(b)", ddl)


class TestGenerateColumnDefinitionDecomposition(unittest.TestCase):
    """Tests for the decomposed helper methods of _generate_column_definition (story 16-20)."""

    def _make_generator(self, dialect="postgresql", columns=None, constraints=None):
        table = MagicMock(spec=Table)
        table.dialect = dialect
        table.system_versioned = False
        table.period_start_column = None
        table.period_end_column = None
        table.constraints = constraints or []
        table.columns = columns or []
        table.format_identifier = lambda x: f'"{x}"'
        return BasicTableDdlGenerator(table)

    def _make_col(self, name="id", data_type="INTEGER", **kwargs):
        col = MagicMock()
        col.name = name
        col.data_type = data_type
        col.nullable = kwargs.pop("nullable", True)
        col.collation = kwargs.pop("collation", None)
        col.is_identity = kwargs.pop("is_identity", False)
        col.identity_seed = kwargs.pop("identity_seed", None)
        col.identity_increment = kwargs.pop("identity_increment", None)
        col.is_computed = kwargs.pop("is_computed", False)
        col.computed_expression = kwargs.pop("computed_expression", None)
        col.computed_stored = kwargs.pop("computed_stored", False)
        col.is_primary_key = kwargs.pop("is_primary_key", False)
        for k, v in kwargs.items():
            setattr(col, k, v)
        return col

    # AC#12.1 — _normalize_column_data_type
    def test_normalize_column_data_type_postgresql_float4(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="FLOAT4(8)")
        result = gen._normalize_column_data_type(col, gen.table.dialect)
        assert result == "FLOAT4"

    # AC#12.2 — _build_collation_clause
    def test_build_collation_clause_mysql(self):
        gen = self._make_generator("mysql")
        col = self._make_col(collation="utf8mb4_unicode_ci")
        result = gen._build_collation_clause(col)
        assert result is not None
        assert "COLLATE" in result
        assert "utf8mb4_unicode_ci" in result

    def test_build_collation_clause_postgresql(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(collation="en_US.UTF-8")
        result = gen._build_collation_clause(col)
        assert result is not None
        assert "COLLATE" in result
        assert "en_US.UTF-8" in result

    # AC#12.3 — _build_temporal_clause
    def test_build_temporal_clause_non_sqlserver_returns_none(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(name="valid_from")
        result = gen._build_temporal_clause(col)
        assert result is None

    # AC#12.4 — _build_identity_clause

    def test_build_identity_clause_mysql(self):
        gen = self._make_generator("mysql")
        col = self._make_col(is_identity=True)
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result == "AUTO_INCREMENT"

    # PostgreSQL identity strategy: native types stay pinned.
    def test_build_identity_clause_postgresql_serial_emits_no_clause(self):
        """PG `serial` encodes identity in the type itself — no extra clause."""
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="serial", is_identity=True)
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result is None

    def test_build_identity_clause_postgresql_bigserial_emits_no_clause(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="bigserial", is_identity=True)
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result is None

    def test_build_identity_clause_postgresql_smallserial_emits_no_clause(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="smallserial", is_identity=True)
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result is None

    def test_build_identity_clause_postgresql_int_with_generation_always(self):
        """Modern PG identity column on int with GENERATED ALWAYS."""
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="int4", is_identity=True, identity_generation="ALWAYS")
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result == "GENERATED ALWAYS AS IDENTITY"

    def test_build_identity_clause_postgresql_int_with_generation_by_default(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="int4", is_identity=True, identity_generation="BY DEFAULT")
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result == "GENERATED BY DEFAULT AS IDENTITY"

    def test_build_identity_clause_postgresql_int_no_generation_defaults_by_default(self):
        """`is_identity=True` on int* without identity_generation -> default to BY DEFAULT."""
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="int4", is_identity=True)
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result == "GENERATED BY DEFAULT AS IDENTITY"

    def test_build_identity_clause_postgresql_not_identity_returns_none(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(data_type="int4", is_identity=False)
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result is None

    def test_build_identity_clause_postgres_alias(self):
        """Dialect 'postgres' alias works the same as 'postgresql'."""
        gen = self._make_generator("postgres")
        col = self._make_col(data_type="serial", is_identity=True)
        result = gen._build_identity_clause(col, gen.table.dialect)
        assert result is None

    # AC#12.5 — _build_not_null_clause
    def test_build_not_null_clause_standard(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(nullable=False)
        result = gen._build_not_null_clause(col, inline_pk_columns=set(), dialect=gen.table.dialect)
        assert result == "NOT NULL"

    # AC#12.6 — _build_computed_clause
    def test_build_computed_clause_postgresql_stored(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(is_computed=True, computed_expression="a + b", computed_stored=True)
        clause, new_parts0 = gen._build_computed_clause(col)
        assert clause == "GENERATED ALWAYS AS (a + b) STORED"
        assert new_parts0 is None

    def test_build_computed_clause_mysql_stored_vs_virtual(self):
        gen = self._make_generator("mysql")
        col_stored = self._make_col(
            is_computed=True, computed_expression="x*2", computed_stored=True
        )
        clause_stored, _ = gen._build_computed_clause(col_stored)
        assert "STORED" in clause_stored

        col_virtual = self._make_col(
            is_computed=True, computed_expression="x*2", computed_stored=False
        )
        clause_virtual, _ = gen._build_computed_clause(col_virtual)
        assert "VIRTUAL" in clause_virtual

    def test_build_computed_clause_not_computed_returns_none(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(is_computed=False)
        clause, new_parts0 = gen._build_computed_clause(col)
        assert clause is None
        assert new_parts0 is None

    # AC#12.7 — _build_inline_pk_clause
    def test_build_inline_pk_clause_single_column(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(name="id")
        result = gen._build_inline_pk_clause(
            col,
            inline_pk_columns={"id"},
            columns_in_skipped_pks=set(),
            pk_constraints=[object()],
            has_composite_pk_final=False,
        )
        assert result == "PRIMARY KEY"

    def test_build_inline_pk_clause_composite_pk_returns_none(self):
        gen = self._make_generator("postgresql")
        col = self._make_col(name="id")
        result = gen._build_inline_pk_clause(
            col,
            inline_pk_columns={"id"},
            columns_in_skipped_pks=set(),
            pk_constraints=[object(), object()],
            has_composite_pk_final=True,
        )
        assert result is None


class TestBasicTableDdlSchemaPrefix:
    """Tests for module-level _schema_prefix_from_object (DEDUP-28).

    The canonical implementation lives in base_generator.py as a module-level
    function; BasicTableDdlGenerator no longer has a local duplicate.
    """

    def test_schema_prefix_from_object_not_in_basic_table_ddl_generator_dict(self):
        """AC#1 — no local copy in BasicTableDdlGenerator.__dict__ (DEDUP-28)."""
        assert "_schema_prefix_from_object" not in BasicTableDdlGenerator.__dict__

    def test_schema_prefix_from_object_no_schema(self):
        obj = MagicMock()
        obj.schema = None
        assert _schema_prefix_from_object(obj) == ""

    def test_schema_prefix_from_object_with_schema(self):
        obj = MagicMock()
        obj.schema = "HR"
        obj.format_identifier.side_effect = lambda x: f'"{x}"'
        result = _schema_prefix_from_object(obj)
        assert result == '"HR".'


class TestMysqlEnumDefaultQuoting(unittest.TestCase):
    """BUG-01: MySQL ENUM DEFAULT must be quoted ('active' not active)."""

    def _make_enum_table(self, default_value: str, data_type: str = "ENUM") -> Table:
        col = SqlColumn(
            "status",
            data_type,
            is_nullable=False,
            default_value=default_value,
            dialect="mysql",
        )
        table = Table("orders", columns=[col], dialect="mysql")
        return table

    def test_enum_default_bare_value_gets_quoted(self):
        table = self._make_enum_table(default_value="active")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        self.assertIn("DEFAULT 'active'", ddl)
        self.assertNotIn("DEFAULT active", ddl)

    def test_enum_default_already_quoted_not_double_quoted(self):
        table = self._make_enum_table(default_value="'active'")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        self.assertIn("DEFAULT 'active'", ddl)
        self.assertNotIn("DEFAULT ''active''", ddl)

    def test_full_enum_type_with_values_preserved(self):
        table = self._make_enum_table(default_value="active", data_type="enum('active','inactive')")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        self.assertIn("DEFAULT 'active'", ddl)

    def test_char_default_still_quoted(self):
        """Regression: existing CHAR quoting must still work."""
        col = SqlColumn(
            "name", "VARCHAR(50)", is_nullable=True, default_value="unknown", dialect="mysql"
        )
        table = Table("t", columns=[col], dialect="mysql")
        gen = BasicTableDdlGenerator(table)
        ddl = gen.generate_create_statement()
        self.assertIn("DEFAULT 'unknown'", ddl)


if __name__ == "__main__":
    unittest.main()
