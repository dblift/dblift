"""Contract tests for :class:`~core.sql_generator.base_generator.BaseSqlGenerator`.

``core/sql_generator`` is an extension point: dialect generators are supplied
by external packages that subclass ``BaseSqlGenerator`` and register the
subclass into ``SqlGeneratorFactory``. Those subclasses inherit the base
class's public methods and their callers live outside this repository, so a
repository-wide "no references" search cannot decide whether a public method
on this class is dead.

The tests below therefore do two things:

* exercise every public method through ``SqlGeneratorFactory.create()`` so a
  method that stops producing usable SQL is caught, and
* pin the set of public method names, so removing one is a deliberate,
  reviewable decision rather than a side effect of a cleanup sweep. See
  ``docs/semver-policy.md`` §1.3.
"""

import pytest

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.generator_factory import SqlGeneratorFactory
from core.sql_generator.options import OrganizationStrategy, ScriptOptions
from core.sql_model.base import SqlColumn, SqlConstraint
from core.sql_model.table import Table

pytestmark = [pytest.mark.unit]

DIALECTS = ["postgresql", "mysql", "oracle", "sqlserver", "sqlite", "duckdb", "db2"]

# The public method surface external subclasses inherit and external callers
# invoke. Adding a name here is a MINOR change; removing one is MAJOR and
# needs the deprecation process in docs/semver-policy.md §3.
PUBLIC_METHOD_SURFACE = frozenset(
    {
        "generate_create_statement",
        "generate_ddl",
        "generate_drop_statements",
        "generate_schema_script",
    }
)


def _schema(dialect):
    """A schema whose two tables have a real foreign-key dependency.

    ``orders`` is listed first so an implementation that ignores the
    dependency ordering ``generate_schema_script`` asks for would emit it
    before the table it references.
    """
    users = Table(
        name="users",
        schema="app",
        columns=[
            SqlColumn("id", "INTEGER", is_nullable=False, is_primary_key=True, dialect=dialect),
            SqlColumn("email", "VARCHAR(255)", dialect=dialect),
        ],
        dialect=dialect,
    )
    orders = Table(
        name="orders",
        schema="app",
        columns=[
            SqlColumn("id", "INTEGER", is_nullable=False, is_primary_key=True, dialect=dialect),
            SqlColumn("user_id", "INTEGER", dialect=dialect),
        ],
        constraints=[
            SqlConstraint(
                constraint_type="FOREIGN KEY",
                name="fk_orders_users",
                column_names=["user_id"],
                reference_table="users",
                reference_columns=["id"],
                dialect=dialect,
            )
        ],
        dialect=dialect,
    )
    return {"tables": [orders, users]}


def test_public_method_surface_is_pinned():
    """Removing a public method from the extension point must be deliberate.

    ``BaseSqlGenerator`` is subclassed and called from outside this
    repository, so "no callers here" is not evidence that a method is dead.
    Update ``PUBLIC_METHOD_SURFACE`` — and ``docs/semver-policy.md`` — in the
    same change that alters the surface.
    """
    actual = {
        name
        for name in vars(BaseSqlGenerator)
        if not name.startswith("_") and callable(vars(BaseSqlGenerator)[name])
    }
    assert actual == set(PUBLIC_METHOD_SURFACE)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_generate_schema_script_renders_ddl_per_type(dialect):
    """The default BY_TYPE organization yields one runnable file per type."""
    generator = SqlGeneratorFactory.create(dialect)

    files = generator.generate_schema_script(_schema(dialect), target_dialect=dialect)

    assert set(files) == {"table.sql"}
    sql = files["table.sql"]
    assert sql.upper().count("CREATE TABLE") == 2
    assert "users" in sql and "orders" in sql
    assert "email" in sql and "user_id" in sql
    # CREATE statements are labelled, DROPs are off by default.
    assert "-- CREATE statements" in sql
    assert "DROP" not in sql.upper()


@pytest.mark.parametrize("dialect", DIALECTS)
def test_generate_schema_script_single_file_orders_dependencies_first(dialect):
    """SINGLE_FILE collapses to schema.sql and keeps dependency order."""
    generator = SqlGeneratorFactory.create(dialect)
    options = ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE)

    files = generator.generate_schema_script(
        _schema(dialect), target_dialect=dialect, options=options
    )

    assert list(files) == ["schema.sql"]
    sql = files["schema.sql"]
    assert sql.index("users") < sql.index("orders")


def test_generate_schema_script_emits_drops_before_creates():
    """``include_drops`` prepends a labelled DROP section."""
    generator = SqlGeneratorFactory.create("postgresql")
    options = ScriptOptions(
        organization=OrganizationStrategy.SINGLE_FILE,
        include_drops=True,
    )

    files = generator.generate_schema_script(
        _schema("postgresql"), target_dialect="postgresql", options=options
    )

    sql = files["schema.sql"]
    assert "-- DROP statements" in sql
    assert "DROP TABLE" in sql.upper()
    assert sql.index("-- DROP statements") < sql.index("-- CREATE statements")


def test_generate_schema_script_returns_no_files_for_an_empty_schema():
    generator = SqlGeneratorFactory.create("postgresql")

    assert generator.generate_schema_script({}) == {}
