"""``render_drop_for_object`` must escape single quotes in container names.

The generated comment splices the container name into a Python snippet
(``context.db.delete_container('<name>')``) by hand-wrapping it in single
quotes. A container name that itself contains a single quote (e.g.
``o'brien_orders``) breaks out of that quoting and produces a snippet that
is not valid Python. Using ``!r`` formatting instead lets Python choose
correct quoting/escaping for the value.
"""

from dblift.db.plugins.cosmosdb.quirks import CosmosdbQuirks


def test_render_drop_for_table_escapes_single_quote_in_container_name():
    quirks = CosmosdbQuirks()
    name = "o'brien_orders"

    comment = quirks.render_drop_for_object(
        obj_type="TABLE",
        obj_name=name,
        schema_prefix="",
        table_name=None,
    )

    assert comment is not None
    assert f"delete_container({name!r})" in comment
    assert "delete_container('o'brien_orders')" not in comment
