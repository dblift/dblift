"""``ADD CONSTRAINT`` must render the FK's referential actions.

``BaseAlterGenerator._format_constraint_definition`` builds the body of every
``ALTER TABLE ... ADD CONSTRAINT`` the diff path emits. It called
``_build_fk_body_sql`` with ``on_delete=None, on_update=None`` hardcoded, so a
foreign key carrying ``ON DELETE SET NULL`` was re-added without it: a model
whose only change is its referential action produced a forward script that
silently dropped the action. The CREATE path has always read the constraint's
own values, so the two paths disagreed about the same constraint.

The CREATE path also honours ``DialectQuirks.table_fk_suppress_on_update`` for
the engine that has no ``ON UPDATE`` clause at all, and
``DialectQuirks.table_fk_supports_restrict`` for the engines whose grammar has
no ``RESTRICT``; the ALTER path must apply the same suppressions or it emits
syntax those engines reject — and must keep ``RESTRICT`` everywhere else,
because it is a stricter constraint than the ``NO ACTION`` default.
"""

from __future__ import annotations

from typing import List, Optional

from dblift.core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
from dblift.core.sql_model.base import ConstraintType, SqlConstraint


class _AlterGenerator(BaseAlterGenerator):
    """Minimal concrete generator: the base class supplies the FK body."""

    def generate_alter_table_statements(  # type: ignore[override]
        self,
        table,
        add_constraints=None,
        drop_constraints=None,
        add_columns=None,
        drop_columns=None,
        modify_columns=None,
    ) -> List[str]:
        statements: List[str] = []
        for constraint in add_constraints or []:
            definition = self._format_constraint_definition(constraint)
            if definition:
                statements.append(f"ALTER TABLE {table} ADD {definition}")
        return statements

    def generate_alter_view_statement(self, view, new_query=None) -> Optional[str]:
        return None

    def _format_identifier(self, identifier: str) -> str:
        return f'"{identifier}"'


def _foreign_key(
    on_delete: Optional[str] = "SET NULL", on_update: Optional[str] = "CASCADE"
) -> SqlConstraint:
    constraint = SqlConstraint(
        name="orders_customer_fk",
        constraint_type=ConstraintType.FOREIGN_KEY,
        column_names=["customer_id"],
        reference_table="customers",
        reference_columns=["id"],
        on_delete=on_delete,
        on_update=on_update,
    )
    constraint.reference_schema = "public"
    return constraint


def test_add_constraint_renders_on_delete_and_on_update() -> None:
    """PostgreSQL supports both clauses, so both must reach the statement."""
    (statement,) = _AlterGenerator("postgresql").generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key()]
    )

    assert "ON DELETE SET NULL" in statement
    assert "ON UPDATE CASCADE" in statement


def test_add_constraint_suppresses_on_update_where_the_engine_has_no_such_clause() -> None:
    """Oracle has no FK ``ON UPDATE``; the CREATE path drops it and so must this one."""
    (statement,) = _AlterGenerator("oracle").generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key()]
    )

    assert "ON DELETE SET NULL" in statement
    assert "ON UPDATE" not in statement


def test_add_constraint_omits_the_implicit_default_action() -> None:
    """``NO ACTION`` is the referential default everywhere, so the clause is noise."""
    (statement,) = _AlterGenerator("postgresql").generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key(on_delete="NO ACTION", on_update="NO ACTION")]
    )

    assert "ON DELETE" not in statement
    assert "ON UPDATE" not in statement


def test_add_constraint_keeps_restrict_where_the_engine_distinguishes_it() -> None:
    """``RESTRICT`` is a different constraint from ``NO ACTION``, not a synonym.

    PostgreSQL checks a ``RESTRICT`` action immediately and cannot defer it, so
    dropping the clause substitutes the deferrable default instead.
    """
    (statement,) = _AlterGenerator("postgresql").generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key(on_delete="RESTRICT", on_update="RESTRICT")]
    )

    assert "ON DELETE RESTRICT" in statement
    assert "ON UPDATE RESTRICT" in statement


def test_add_constraint_omits_restrict_where_the_engine_lacks_the_keyword() -> None:
    """SQL Server's referential-action grammar has no ``RESTRICT`` to emit."""
    (statement,) = _AlterGenerator("sqlserver").generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key(on_delete="RESTRICT", on_update="RESTRICT")]
    )

    assert "ON DELETE" not in statement
    assert "ON UPDATE" not in statement


def test_a_foreign_key_with_no_actions_renders_as_before() -> None:
    """No referential action on the constraint means no clause, exactly as today."""
    (statement,) = _AlterGenerator("postgresql").generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key(on_delete=None, on_update=None)]
    )

    assert statement == (
        'ALTER TABLE orders ADD CONSTRAINT "orders_customer_fk" FOREIGN KEY '
        '("customer_id") REFERENCES "public"."customers" ("id")'
    )
