"""Characterization of statement-facts helper branches the dialect suites leave unexercised.

Each case pins the exact facts ``read_statement_facts`` returns today through the head-name
proof, the PostgreSQL COPY and MERGE readers and the Redshift MERGE reading. The cases pin
outcomes: where a later check returns the same opaque result, removing the earlier branch alone
is not caught.
"""

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import StatementFacts


@pytest.mark.parametrize(
    "sql",
    [
        # The CTE list ends after a comma: ``#`` comments out the statement for the engine.
        "WITH a AS (SELECT 1), # INSERT INTO t VALUES (1)",
        # The CTE body is the last token: no statement follows it.
        "WITH a AS (SELECT 1) # INSERT INTO t VALUES (1)",
        # The CTE body never closes: ``#`` comments out its closing parenthesis.
        "WITH a AS (SELECT 1 # )\nINSERT INTO t VALUES (1)",
    ],
)
def test_a_cte_list_the_mysql_tokens_do_not_complete_proves_no_target(sql):
    assert read_statement_facts(sql, dialect="mysql") == StatementFacts(
        "INSERT", "DML", diagnostic="mysql grammar is not modelled for this statement"
    )


def test_a_name_the_tokens_read_as_one_number_proves_no_target():
    assert read_statement_facts("UPDATE 1.5 SET a = 1", dialect="postgres") == StatementFacts(
        "UPDATE", "DML", diagnostic="postgres grammar is not modelled for this statement"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "COPY .t FROM STDIN",  # a leading dot before the table name
        "COPY INTO s.t FROM STDIN",  # INTO shifts the schema off its dot
        "COPY INTO t (a) FROM STDIN",  # INTO shifts the table off its column list
        "COPY INTO to FROM STDIN",  # the table named ``to`` reads as the direction word
    ],
)
def test_a_postgres_copy_head_the_tokens_do_not_spell_is_opaque(sql):
    assert read_statement_facts(sql, dialect="postgres") == StatementFacts(
        "COPY", "UNKNOWN", diagnostic="postgres COPY source or destination is opaque"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "MERGE INTO (SELECT 1) USING s ON a=b WHEN MATCHED THEN DELETE",  # target is no table
        "MERGE INTO t USING unnest(ARRAY[1]) AS u(a) ON t.a=u.a WHEN MATCHED THEN DELETE",
        "MERGE INTO t USING s ON t.a = s.a WHEN NOT MATCHED THEN INSERT (a) VALUES",
    ],
)
def test_a_postgres_merge_the_reader_does_not_model_is_classified_from_its_head(sql):
    assert read_statement_facts(sql, dialect="postgres") == StatementFacts(
        "MERGE", "UNKNOWN", diagnostic="postgres MERGE effects are not modelled"
    )


def test_a_redshift_merge_into_a_subquery_has_no_target():
    sql = "MERGE INTO (SELECT 1) USING s ON a=b WHEN MATCHED THEN DELETE"
    assert read_statement_facts(sql, dialect="redshift") == StatementFacts(
        "MERGE", "DML", diagnostic="redshift MERGE sources and actions are not read"
    )
