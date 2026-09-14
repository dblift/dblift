"""``CREATE TABLE`` must keep a foreign key's ``RESTRICT`` where it means something.

``_build_fk_body_sql`` suppressed ``NO ACTION`` and ``RESTRICT`` together, on
every dialect, so a model carrying ``ON DELETE RESTRICT`` reached the SQL with
no action clause at all — which the engine then reads as its ``NO ACTION``
default. On PostgreSQL, SQLite and Db2 that is a different constraint:
``RESTRICT`` is checked immediately and cannot be deferred.

The suppression is now a per-engine decision
(``DialectQuirks.table_fk_supports_restrict``), and the CREATE and ALTER paths
must reach the same decision for the same constraint — they render the same
foreign key and a disagreement between them is how a diff produces a script
that does not reproduce the model.
"""

from __future__ import annotations

import re
from typing import List, Optional, Set

import pytest

from dblift.core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
from dblift.core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator
from dblift.core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from dblift.core.sql_model.table import Table

pytestmark = [pytest.mark.unit]

# Engines whose grammar accepts RESTRICT as a referential action, so the clause
# is worth emitting. Db2 also allows it on ON UPDATE, where its only
# alternative is NO ACTION.
KEEPS_RESTRICT = ["postgresql", "cockroachdb", "sqlite", "mysql", "mariadb", "db2", "snowflake"]

# Engines that cannot express it: SQL Server and Oracle have no such keyword,
# Redshift takes no referential action clause at all, and DuckDB parses
# RESTRICT but records NO ACTION in its own catalogue.
DROPS_RESTRICT = ["sqlserver", "oracle", "redshift", "duckdb"]

_ACTION_CLAUSE = re.compile(r"ON (?:DELETE|UPDATE) (?:NO ACTION|RESTRICT|CASCADE|SET NULL)")


class _AlterGenerator(BaseAlterGenerator):
    """Minimal concrete generator so the ALTER body can be compared to CREATE."""

    def generate_alter_table_statements(  # type: ignore[override]
        self,
        table,
        add_constraints=None,
        drop_constraints=None,
        add_columns=None,
        drop_columns=None,
        modify_columns=None,
    ) -> List[str]:
        return [
            definition
            for definition in (self._format_constraint_definition(c) for c in add_constraints or [])
            if definition
        ]

    def generate_alter_view_statement(self, view, new_query=None) -> Optional[str]:
        return None

    def _format_identifier(self, identifier: str) -> str:
        return f'"{identifier}"'


def _table(dialect: str, reference_table: str = "customers", action: str = "RESTRICT") -> Table:
    return Table(
        name="orders",
        schema="app",
        columns=[
            SqlColumn("id", "INTEGER", dialect=dialect),
            SqlColumn("customer_id", "INTEGER", dialect=dialect),
        ],
        constraints=[_foreign_key(dialect, reference_table, action)],
        dialect=dialect,
    )


def _foreign_key(dialect: str, reference_table: str, action: str) -> SqlConstraint:
    return SqlConstraint(
        name="orders_customer_fk",
        constraint_type=ConstraintType.FOREIGN_KEY,
        column_names=["customer_id"],
        reference_table=reference_table,
        reference_columns=["id"],
        on_delete=action,
        on_update=action,
        dialect=dialect,
    )


def _action_clauses(sql: str) -> Set[str]:
    return set(_ACTION_CLAUSE.findall(sql))


@pytest.mark.parametrize("dialect", KEEPS_RESTRICT)
def test_create_table_keeps_restrict_where_the_engine_accepts_it(dialect: str) -> None:
    sql = BasicTableDdlGenerator(_table(dialect)).generate_create_statement()

    assert "ON DELETE RESTRICT" in sql
    assert "ON UPDATE RESTRICT" in sql


@pytest.mark.parametrize("dialect", DROPS_RESTRICT)
def test_create_table_drops_restrict_where_the_engine_cannot_express_it(dialect: str) -> None:
    sql = BasicTableDdlGenerator(_table(dialect)).generate_create_statement()

    assert "RESTRICT" not in sql
    assert "ON DELETE" not in sql
    assert "ON UPDATE" not in sql


@pytest.mark.parametrize("dialect", KEEPS_RESTRICT + DROPS_RESTRICT)
def test_no_action_is_still_omitted_everywhere(dialect: str) -> None:
    """Only ``RESTRICT`` changes: the engine default stays unwritten."""
    sql = BasicTableDdlGenerator(_table(dialect, action="NO ACTION")).generate_create_statement()

    assert "ON DELETE" not in sql
    assert "ON UPDATE" not in sql


@pytest.mark.parametrize("dialect", KEEPS_RESTRICT + DROPS_RESTRICT)
def test_create_and_alter_render_the_same_action_clauses(dialect: str) -> None:
    """One constraint, two paths — a diff that re-adds it must not change it."""
    create_sql = BasicTableDdlGenerator(_table(dialect)).generate_create_statement()
    (alter_definition,) = _AlterGenerator(dialect).generate_alter_table_statements(
        "orders", add_constraints=[_foreign_key(dialect, "customers", "RESTRICT")]
    )

    assert _action_clauses(create_sql) == _action_clauses(alter_definition)


def test_a_self_referencing_key_added_via_alter_keeps_restrict() -> None:
    """Db2 cannot declare a self-referencing FK inline, so it takes the ALTER path.

    That path calls the same builder with ``suppress_on_update=False``, and it
    is the only caller a CREATE-statement assertion never reaches.
    """
    generator = BasicTableDdlGenerator(_table("db2", reference_table="orders"))

    assert "FOREIGN KEY" not in generator.generate_create_statement()
    (statement,) = generator.generate_alter_self_referencing_fks()
    assert "ON DELETE RESTRICT" in statement
    assert "ON UPDATE RESTRICT" in statement
