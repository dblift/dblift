"""Catalog view security options survive extraction and serialization."""

import pytest

from dblift.core.sql_model.view import View
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


@pytest.mark.parametrize(
    "row, expected",
    [({"security_barrier": True}, True), ({"security_barrier": False}, None), ({}, None)],
)
def test_security_barrier_from_catalog(row, expected):
    view = View(name="protected_view", query="SELECT 1")
    PostgresqlQuirks().enrich_view_from_row(view, row)
    assert view.get_dialect_option("postgresql", "security_barrier") is expected
