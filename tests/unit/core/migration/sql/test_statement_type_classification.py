"""``get_statement_type`` classifies a statement the way the dialect's own rules always did.

PostgreSQL (and the engines that share its rules) and Oracle name statement words the generic
keyword rules do not know: transaction control and maintenance commands are DDL, ``COPY`` / ``CALL``
/ ``LOCK`` / ``PREPARE`` are DML, ``VALUES`` / ``TABLE`` are queries. The journal records object
changes only for DDL and DML, and a callback reads rows only from a QUERY, so these answers matter.
"""

import json
from pathlib import Path

import pytest

from dblift.core.migration.sql.statement_reader import StatementReader

pytestmark = pytest.mark.unit

PG_FAMILY = ("postgresql", "redshift", "cockroachdb")

PG_SHAPES = [
    ("CREATE TEMP TABLE tmp (id INT);", "DDL"),
    ("ALTER TABLE users ADD COLUMN email TEXT;", "DDL"),
    ("DROP TABLE IF EXISTS users;", "DDL"),
    ("CREATE INDEX idx_users_email ON users (email);", "DDL"),
    ("CREATE VIEW active_users AS SELECT * FROM users WHERE active = true;", "DDL"),
    ("CREATE FUNCTION f() RETURNS INT AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql;", "DDL"),
    ("INSERT INTO users (name) VALUES ('Alice');", "DML"),
    ("UPDATE users SET name = 'Bob' WHERE id = 1;", "DML"),
    ("DELETE FROM users WHERE id = 1;", "DML"),
    ("SELECT * FROM users;", "QUERY"),
    ("BEGIN", "DDL"),
    ("COMMIT", "DDL"),
    ("ROLLBACK", "DDL"),
    ("START TRANSACTION", "DDL"),
    ("SAVEPOINT s1", "DDL"),
    ("RELEASE SAVEPOINT s1", "DDL"),
    ("END", "DDL"),
    ("ABORT", "DDL"),
    ("BEGIN TRANSACTION", "DDL"),
    ("COMMIT WORK", "DDL"),
    ("ROLLBACK TO SAVEPOINT s1", "DDL"),
    ("VACUUM a", "DDL"),
    ("ANALYZE a", "DDL"),
    ("REINDEX TABLE a", "DDL"),
    ("CLUSTER a", "DDL"),
    ("COPY a FROM stdin", "DML"),
    ("COPY t (id) FROM '/tmp/f.csv'", "DML"),
    ("CALL p()", "DML"),
    ("LOCK TABLE a", "DML"),
    ("PREPARE p AS SELECT 1", "DML"),
    ("DEALLOCATE p", "DML"),
    ("VALUES (1)", "QUERY"),
    ("TABLE a", "QUERY"),
    ("", "UNKNOWN"),
    ("   ", "UNKNOWN"),
    ("XYZZY 1 2 3;", "UNKNOWN"),
    (
        "WITH deleted AS (DELETE FROM src WHERE id = 1 RETURNING id) "
        "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted",
        "DML",
    ),
    (
        "WITH x AS (UPDATE src SET id = id RETURNING id) INSERT INTO app_logs(msg) SELECT 'x' FROM x",
        "DML",
    ),
    ("WITH x AS (INSERT INTO src VALUES (99) RETURNING id) SELECT * FROM x", "QUERY"),
    ("WITH x AS (SELECT 1) SELECT * FROM x", "QUERY"),
    (
        "WITH deleted AS (DELETE FROM src WHERE id = 1 /* RETURNING trap */ RETURNING id) "
        "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted",
        "DML",
    ),
]

ORACLE_SHAPES = [
    ("CREATE TABLE test (id NUMBER)", "DDL"),
    ("ALTER TABLE test ADD column1 VARCHAR2(50)", "DDL"),
    ("DROP TABLE test", "DDL"),
    ("CREATE INDEX idx_test ON test(id)", "DDL"),
    ("CREATE OR REPLACE VIEW test_view AS SELECT * FROM test", "DDL"),
    ("CREATE SEQUENCE test_seq", "DDL"),
    ("GRANT SELECT ON test TO user1", "DDL"),
    ("ANALYZE TABLE test COMPUTE STATISTICS", "DDL"),
    ("AUDIT SELECT ON test", "DDL"),
    ("NOAUDIT SELECT ON test", "DDL"),
    ("INSERT INTO test VALUES (1)", "DML"),
    ("UPDATE test SET id = 2", "DML"),
    ("DELETE FROM test WHERE id = 1", "DML"),
    ("MERGE INTO test USING other ON (test.id = other.id)", "DML"),
    ("CALL DBMS_STATS.GATHER_TABLE_STATS('SCHEMA', 'TABLE')", "DML"),
    ("CALL proc()", "DML"),
    ("EXECUTE IMMEDIATE 'DROP TABLE temp'", "DML"),
    ("EXEC sp_test", "DML"),
    ("SELECT * FROM test", "QUERY"),
    ("WITH cte AS (SELECT * FROM test) SELECT * FROM cte", "QUERY"),
    ("EXPLAIN PLAN FOR SELECT * FROM test", "QUERY"),
    ("", "UNKNOWN"),
    ("INVALID SQL", "UNKNOWN"),
    # Better than before: the outer statement of a CTE decides (it was QUERY).
    ("WITH c AS (SELECT 1 FROM dual) INSERT INTO t SELECT * FROM c", "DML"),
]


@pytest.mark.parametrize("dialect", PG_FAMILY)
@pytest.mark.parametrize(("sql", "expected"), PG_SHAPES)
def test_postgresql_family_statement_types(dialect, sql, expected):
    assert StatementReader(dialect).get_statement_type(sql) == expected


@pytest.mark.parametrize(("sql", "expected"), ORACLE_SHAPES)
def test_oracle_statement_types(sql, expected):
    assert StatementReader("oracle").get_statement_type(sql) == expected


FIXTURE = json.loads(
    Path(__file__).with_name("statement_type_develop_expected.json").read_text(encoding="utf-8")
)
INPUTS = {
    row["id"]: row["sql"]
    for row in (
        json.loads(line)
        for line in (
            Path(__file__).resolve().parents[4] / "support" / "facts_corpus" / "inputs.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
    )
}


@pytest.mark.parametrize("dialect", sorted(FIXTURE["expected"]))
def test_the_facts_corpus_keeps_the_classification_of_the_release_before(dialect):
    wrong = {
        input_id: (expected, StatementReader(dialect).get_statement_type(INPUTS[input_id]))
        for input_id, expected in FIXTURE["expected"][dialect].items()
        if StatementReader(dialect).get_statement_type(INPUTS[input_id]) != expected
    }
    assert wrong == {}


def test_the_one_deliberate_difference_is_the_oracle_cte_with_a_write():
    for input_id, (before, now) in FIXTURE["improved"].items():
        assert (before, now) == ("QUERY", "DML")
        assert StatementReader("oracle").get_statement_type(INPUTS[input_id]) == now


@pytest.mark.parametrize("dialect", PG_FAMILY)
def test_a_command_word_alone_or_before_its_semicolon_is_classified(dialect):
    for input_id, (before, now) in FIXTURE["bare_words"].items():
        assert before == "UNKNOWN"
        assert StatementReader(dialect).get_statement_type(INPUTS[input_id]) == now


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgresql", "COPY t (id) FROM '/tmp/f.csv'"),
        ("redshift", "COPY t (id) FROM 's3://b/k' IAM_ROLE 'arn:aws:iam::1:role/r'"),
        ("postgresql", "INSERT INTO t VALUES (1)"),
    ],
)
def test_a_copy_into_a_table_is_tracked_by_the_journal(dialect, sql):
    from unittest.mock import MagicMock

    from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
    from dblift.db.provider_registry import ProviderRegistry

    provider = MagicMock()
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    journal.capture_objects = True
    service = SqlExecutionService(
        provider,
        StatementReader(dialect),
        journal=journal,
        schema="public",
        quirks=ProviderRegistry.get_quirks(dialect),
    )

    service.execute_statement(sql, 0)

    assert journal.record_object_changes.call_count == 1
