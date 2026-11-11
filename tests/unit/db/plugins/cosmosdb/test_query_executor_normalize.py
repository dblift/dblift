"""Characterization of the container-alias normalization applied to Cosmos DB SELECT queries."""

import pytest

from dblift.db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor


def _normalize(sql: str, container: str = "orders") -> str:
    executor = CosmosDbQueryExecutor.__new__(CosmosDbQueryExecutor)
    return executor._normalize_cosmos_sql(sql, container)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        pytest.param("SELECT VALUE 1", "SELECT VALUE 1", id="no-from-clause-is-unchanged"),
        pytest.param(
            "SELECT 'a,b', \"x(y\", id FROM orders",
            "SELECT c.'a,b', c.\"x(y\", c.id FROM orders c ",
            id="quoted-comma-and-parenthesis-stay-in-one-field",
        ),
        pytest.param(
            "SELECT CONCAT(a, b) AS ab FROM orders",
            "SELECT c.CONCAT(a, b) AS ab FROM orders c ",
            id="comma-inside-parentheses-stays-in-one-field",
        ),
        pytest.param(
            "SELECT id, name FROM orders",
            "SELECT c.id, c.name FROM orders c ",
            id="top-level-comma-splits-fields",
        ),
        pytest.param(
            "SELECT id, FROM orders",
            "SELECT c.id FROM orders c ",
            id="trailing-empty-field-is-dropped",
        ),
        pytest.param(
            "SELECT c.id, name, COUNT(1) FROM orders",
            "SELECT c.id, c.name, COUNT(1) FROM orders c ",
            id="aliased-and-aggregate-fields-are-kept",
        ),
        pytest.param(
            "SELECT * FROM orders ORDER BY ts DESC",
            "SELECT * FROM orders c ORDER BY c.ts DESC",
            id="order-by-field-is-prefixed",
        ),
        pytest.param(
            "SELECT id FROM orders ORDER BY ts",
            "SELECT c.id FROM orders c ORDER BY c.ts",
            id="order-by-is-read-after-the-select-list-was-rewritten",
        ),
        pytest.param(
            "SELECT * FROM orders WHERE status = 'open'",
            "SELECT * FROM orders c WHERE c.status = 'open'",
            id="where-field-is-prefixed",
        ),
        pytest.param(
            "SELECT * FROM orders WHERE status = 'open' ORDER BY 1",
            "SELECT * FROM orders c WHERE c.status = 'open' ORDER BY 1",
            id="where-field-before-order-by-is-prefixed",
        ),
        pytest.param(
            "SELECT * FROM orders WHERE status = 'open' ORDER BY ts",
            "SELECT * FROM orders c WHERE status = 'open' ORDER BY c.ts",
            id="where-is-left-alone-once-order-by-holds-an-alias",
        ),
        pytest.param(
            "SELECT * FROM orders WHERE x > 1 AND c.y = 2",
            "SELECT * FROM orders c WHERE x > 1 AND c.y = 2",
            id="where-holding-an-alias-is-left-alone",
        ),
    ],
)
def test_normalize_cosmos_sql(sql, expected):
    assert _normalize(sql) == expected
