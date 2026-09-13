"""``ADD CONSTRAINT`` must render the FK's referential actions.

``BaseAlterGenerator._format_constraint_definition`` builds the body of every
``ALTER TABLE ... ADD CONSTRAINT`` the diff path emits. It called
``_build_fk_body_sql`` with ``on_delete=None, on_update=None`` hardcoded, so a
foreign key carrying ``ON DELETE SET NULL`` was re-added without it: a model
whose only change is its referential action produced a forward script that
silently dropped the action. The CREATE path has always read the constraint's
own values, so the two paths disagreed about the same constraint.

The CREATE path also honours ``DialectQuirks.table_fk_suppress_on_update`` for
the engine that has no ``ON UPDATE`` clause at all; the ALTER path must apply
the same suppression or it emits syntax that engine rejects.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

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


@pytest.mark.parametrize("action", ["NO ACTION", "RESTRICT"])
def test_add_constraint_omits_the_implicit_default_actions(action: str) -> None:
    """The builder suppresses both actions, so ALTER emits what CREATE emits.

    ``basic_table_ddl_generator`` suppresses ``NO ACTION`` and ``RESTRICT``
    alike, so a modelled ``ON DELETE RESTRICT`` reaches the SQL with no action
    clause at all. That suppression predates this path and is separately wrong:
    ``RESTRICT`` is not the PostgreSQL default and, unlike ``NO ACTION``, its
    check cannot be deferred. What this test pins is only that the ALTER path
    renders the same clause the CREATE path does; changing the suppression
    would be a change to both.
    """
    (statement,) = _AlterGenerator("postgresql").generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key(on_delete=action, on_update=action)]
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
