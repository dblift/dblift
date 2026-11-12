"""Characterization of the diagnostic a PostgreSQL CREATE led by an unread WITH keeps."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject

pytestmark = pytest.mark.unit
PG = "postgres"  # lint: allow-dialect-string: test


@pytest.mark.parametrize(
    "sql, created, diagnostic",
    [
        (
            "WITH x AS (DELETE FROM t RETURNING *) CREATE TABLE u AS SELECT * FROM x",
            NamedObject("u", SqlObjectType.TABLE, "created"),
            "postgres CREATE with a data-modifying CTE is not read",
        ),
        (
            "WITH x AS (SELECT 1) CREATE VIEW v AS SELECT * FROM x",
            NamedObject("v", SqlObjectType.VIEW, "created"),
            "postgres CTE source scopes or effects are opaque to statement facts",
        ),
    ],
)
def test_a_create_led_by_an_unread_with_keeps_its_object_and_says_why(sql, created, diagnostic):
    facts = read_statement_facts(sql, dialect=PG)

    assert (facts.operation, facts.kind, facts.objects) == ("CREATE", "DDL", (created,))
    assert facts.diagnostic == diagnostic
