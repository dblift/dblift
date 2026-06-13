"""Tests for _is_self_referencing_fk() and _build_fk_body() helpers in BasicTableDdlGenerator."""

import unittest

import pytest

from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table

pytestmark = [pytest.mark.unit]


def _make_table(name="users", schema=None, dialect=None):
    col = SqlColumn("id", "INTEGER", is_nullable=False)
    return Table(name, columns=[col], schema=schema, dialect=dialect)


def _make_fk_constraint(
    ref_table=None,
    ref_schema=None,
    column_names=None,
    ref_columns=None,
    name=None,
    on_delete=None,
    on_update=None,
):
    c = SqlConstraint(
        constraint_type=ConstraintType.FOREIGN_KEY,
        name=name,
        column_names=column_names or [],
        reference_table=ref_table,
        reference_columns=ref_columns,
        on_delete=on_delete,
        on_update=on_update,
    )
    c.reference_schema = ref_schema
    return c


class TestIsSelfReferencingFk(unittest.TestCase):
    """Tests for _is_self_referencing_fk()."""

    def test_same_table_same_schema(self):
        table = _make_table("users", schema="public")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="users", ref_schema="public")
        self.assertTrue(gen._is_self_referencing_fk(fk))

    def test_different_table(self):
        table = _make_table("users", schema="public")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="orders", ref_schema="public")
        self.assertFalse(gen._is_self_referencing_fk(fk))

    def test_case_insensitive_match(self):
        table = _make_table("Users", schema="Public")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="USERS", ref_schema="PUBLIC")
        self.assertTrue(gen._is_self_referencing_fk(fk))

    def test_schema_none_both_sides(self):
        table = _make_table("users", schema=None)
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="users", ref_schema=None)
        self.assertTrue(gen._is_self_referencing_fk(fk))

    def test_schema_none_one_side(self):
        table = _make_table("users", schema="public")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="users", ref_schema=None)
        self.assertTrue(gen._is_self_referencing_fk(fk))

    def test_schema_none_table_but_ref_has_schema(self):
        """Reverse of test_schema_none_one_side: table has no schema but FK specifies one."""
        table = _make_table("users", schema=None)
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="users", ref_schema="public")
        # One side is None → assume same schema
        self.assertTrue(gen._is_self_referencing_fk(fk))

    def test_ref_table_none(self):
        table = _make_table("users")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table=None)
        self.assertFalse(gen._is_self_referencing_fk(fk))

    def test_different_schema_same_table_name(self):
        table = _make_table("users", schema="public")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="users", ref_schema="other")
        self.assertFalse(gen._is_self_referencing_fk(fk))


class TestBuildFkBody(unittest.TestCase):
    """Tests for _build_fk_body()."""

    def test_no_columns_returns_none(self):
        table = _make_table("users")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table="orders", column_names=[])
        self.assertIsNone(gen._build_fk_body(fk))

    def test_no_ref_table_returns_none(self):
        table = _make_table("users")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(ref_table=None, column_names=["order_id"])
        self.assertIsNone(gen._build_fk_body(fk))

    def test_basic_fk(self):
        table = _make_table("orders")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(
            ref_table="users",
            column_names=["user_id"],
            ref_columns=["id"],
        )
        result = gen._build_fk_body(fk)
        self.assertIsNotNone(result)
        self.assertIn("FOREIGN KEY (", result)
        self.assertIn("REFERENCES", result)
        self.assertIn("user_id", result)
        self.assertIn("(id)", result)

    def test_on_delete_cascade(self):
        table = _make_table("orders")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(
            ref_table="users",
            column_names=["user_id"],
            ref_columns=["id"],
            on_delete="CASCADE",
        )
        result = gen._build_fk_body(fk)
        self.assertIn("ON DELETE CASCADE", result)

    def test_suppress_on_update(self):
        table = _make_table("orders")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(
            ref_table="users",
            column_names=["user_id"],
            ref_columns=["id"],
            on_update="CASCADE",
        )
        result_with = gen._build_fk_body(fk, suppress_on_update=False)
        self.assertIn("ON UPDATE CASCADE", result_with)

        result_without = gen._build_fk_body(fk, suppress_on_update=True)
        self.assertNotIn("ON UPDATE", result_without)

    def test_with_reference_schema(self):
        table = _make_table("orders")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(
            ref_table="users",
            ref_schema="auth",
            column_names=["user_id"],
            ref_columns=["id"],
        )
        result = gen._build_fk_body(fk)
        self.assertIn("auth", result)
        self.assertIn("users", result)

    def test_on_delete_no_action_excluded(self):
        table = _make_table("orders")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(
            ref_table="users",
            column_names=["user_id"],
            ref_columns=["id"],
            on_delete="NO ACTION",
        )
        result = gen._build_fk_body(fk)
        self.assertNotIn("ON DELETE", result)

    def test_dedup_columns(self):
        table = _make_table("orders")
        gen = BasicTableDdlGenerator(table)
        fk = _make_fk_constraint(
            ref_table="users",
            column_names=["user_id", "user_id"],
            ref_columns=["id"],
        )
        result = gen._build_fk_body(fk)
        self.assertIsNotNone(result)
        self.assertEqual(result.count("user_id"), 1)


if __name__ == "__main__":
    unittest.main()
