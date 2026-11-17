"""Db2 read queries: which forms are proven complete (``events`` empty) and which are not."""

import pytest

from dblift.db.plugins.db2.parser.statement_facts import Db2StatementFactsReader

READ = Db2StatementFactsReader(None).read


def _nested(levels: int) -> str:
    query = "SELECT 1"
    for k in range(levels):
        query = f"WITH q{k} AS ({query}) SELECT * FROM q{k}"
    return query


@pytest.mark.parametrize(
    ("sql", "events"),
    [
        pytest.param("WITH c AS () SELECT 1", None, id="empty-cte-body-is-not-proven"),
        pytest.param(_nested(16), frozenset(), id="sixteen-nested-ctes-are-proven"),
        pytest.param(_nested(17), None, id="seventeen-nested-ctes-are-not-proven"),
        pytest.param("WITH c AS x SELECT 1) SELECT 2", None, id="cte-body-without-parenthesis"),
        pytest.param(
            "WITH a AS (SELECT 1), b AS (SELECT 2) SELECT * FROM b",
            frozenset(),
            id="comma-separated-ctes-are-proven",
        ),
        pytest.param("VALUES (1 2", None, id="values-row-without-closing-parenthesis"),
        pytest.param("VALUES (1)", frozenset(), id="values-row-with-closing-parenthesis"),
    ],
)
def test_read_query_completeness(sql, events):
    facts = READ(sql)

    assert (facts.operation, facts.kind, facts.diagnostic, facts.error) == (
        sql.split()[0],
        "QUERY",
        None,
        None,
    )
    assert facts.events == events
