"""``MongodbQuirks.render_drop_for_object`` — DBLIFT-NOSQL-001 regression.

MongoDB has no SQL DDL path, so before this override every DROP fell through
to the relational fallback in ``core/sql_generator/sql_generator.py`` and
produced statements like ``DROP TABLE IF EXISTS orders CASCADE;`` — which
then made a ``.sql`` migration for a NoSQL store and got rejected outright.
``render_drop_for_object`` must intercept every object type and render an
explanatory comment instead of SQL.
"""

import pytest

from core.sql_generator.sql_generator import SqlGenerator
from core.sql_model.index import Index
from core.sql_model.table import Table
from db.plugins.mongodb.quirks import MongodbQuirks


def test_render_drop_for_table_names_drop_collection():
    quirks = MongodbQuirks()

    comment = quirks.render_drop_for_object(
        obj_type="TABLE",
        obj_name="orders",
        schema_prefix="",
        table_name=None,
    )

    assert comment is not None
    assert "drop_collection" in comment
    assert "orders" in comment


def test_render_drop_for_index_names_drop_index():
    quirks = MongodbQuirks()

    comment = quirks.render_drop_for_object(
        obj_type="INDEX",
        obj_name="idx_email",
        schema_prefix="",
        table_name="orders",
    )

    assert comment is not None
    assert "drop_index" in comment
    assert "idx_email" in comment
    # Unlike CosmosDB, MongoDB indexes are real, individually named,
    # droppable objects — the comment must reference the collection they
    # belong to (available via the ``table_name`` parameter), not describe
    # them as governed by an indexing policy.
    assert "orders" in comment
    assert "indexing policy" not in comment


def test_render_drop_for_view_names_drop_collection():
    """MongoDB views (``db.createView``) are real, listed in ``listCollections``
    as ``type: "view"``, queryable, and dropped exactly like a collection —
    unlike CosmosDB, which has no view concept at all. A prior draft of this
    override wrongly copied Cosmos's "does not support views" text; guard
    against that regression explicitly.
    """
    quirks = MongodbQuirks()

    comment = quirks.render_drop_for_object(
        obj_type="VIEW",
        obj_name="big_orders",
        schema_prefix="",
        table_name=None,
    )

    assert comment is not None
    assert "drop_collection" in comment
    assert "big_orders" in comment
    assert "does not support views" not in comment


def test_render_drop_for_materialized_view_names_drop_collection():
    """MongoDB's "on-demand materialized view" pattern ($merge) writes to an
    ordinary collection — there is no separate persisted catalog object, so
    it drops the same way a collection does.
    """
    quirks = MongodbQuirks()

    comment = quirks.render_drop_for_object(
        obj_type="MATERIALIZED_VIEW",
        obj_name="daily_totals",
        schema_prefix="",
        table_name=None,
    )

    assert comment is not None
    assert "drop_collection" in comment
    assert "daily_totals" in comment


@pytest.mark.parametrize("obj_type", ["TABLE", "INDEX", "VIEW", "MATERIALIZED_VIEW"])
def test_no_branch_returns_sql(obj_type):
    """Every branch must return a comment, never a runnable DROP statement."""
    quirks = MongodbQuirks()

    comment = quirks.render_drop_for_object(
        obj_type=obj_type,
        obj_name="thing",
        schema_prefix="",
        table_name="thing" if obj_type == "INDEX" else None,
    )

    assert comment is not None
    assert not comment.upper().startswith("DROP ")


@pytest.mark.parametrize(
    "obj_type",
    [
        "SEQUENCE",
        "PROCEDURE",
        "FUNCTION",
        "TRIGGER",
        "PACKAGE",
        "SYNONYM",
    ],
)
def test_unsupported_object_types_render_explanatory_comment(obj_type):
    """Object types MongoDB has no concept of still render something, not None."""
    quirks = MongodbQuirks()

    comment = quirks.render_drop_for_object(
        obj_type=obj_type,
        obj_name="thing",
        schema_prefix="",
        table_name=None,
    )

    assert comment is not None
    assert comment.strip() != ""
    assert not comment.upper().startswith("DROP ")


def test_table_drop_via_sql_generator_does_not_emit_drop_table():
    """Guard for the actual defect: DROP TABLE must not appear for MongoDB."""
    table = Table(name="orders", dialect="mongodb")
    generator = SqlGenerator(default_dialect="mongodb")

    sql = generator.generate_drop_statements([table])

    assert "DROP TABLE" not in sql.upper()


def test_index_drop_via_sql_generator_does_not_emit_drop_index():
    """Guard for the actual defect: DROP INDEX must not appear for MongoDB."""
    index = Index(name="idx_email", table_name="orders", columns=["email"], dialect="mongodb")
    generator = SqlGenerator(default_dialect="mongodb")

    sql = generator.generate_drop_statements([index])

    assert "DROP INDEX" not in sql.upper()
