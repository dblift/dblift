"""``find_issues``: the rules ``validate-sql`` applies to one script."""

from __future__ import annotations

import logging

import pytest

from dblift.core.migration.sql.lint_rules import ERROR, INFO, SEVERITY, WARNING, find_issues
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit


def _codes(sql: str, dialect: str) -> list:
    return [f.code for f in find_issues(analyse_script(sql, dialect), dialect)]


@pytest.mark.parametrize(
    "dialect, sql, expected",
    [
        ("postgresql", "DROP TABLE users;", ["drop-table", "pg-missing-lock-timeout"]),
        ("mysql", "DROP TABLE users;", ["drop-table"]),
        ("mysql", "TRUNCATE users;", ["truncate"]),
        ("mysql", "ALTER TABLE users DROP COLUMN email;", ["drop-column"]),
        ("mysql", "DELETE FROM users;", ["dml-no-where"]),
        ("mysql", "DELETE FROM users WHERE id = 1;", []),
        ("mysql", "ALTER TABLE users ADD COLUMN age INT NOT NULL;", ["add-not-null-no-default"]),
        ("mysql", "ALTER TABLE users ADD COLUMN age INT NOT NULL DEFAULT 0;", []),
        ("mysql", "ALTER TABLE users RENAME COLUMN a TO b;", ["rename-column"]),
        ("mysql", "RENAME TABLE a TO b;", ["rename-table"]),
        ("mysql", "ALTER TABLE users MODIFY COLUMN age BIGINT;", ["alter-column-type"]),
        ("sqlserver", "EXEC sp_rename 'users.a', 'b', 'COLUMN';", ["rename-column"]),
        ("sqlserver", "ALTER TABLE users ALTER COLUMN age BIGINT;", ["alter-column-type"]),
        ("oracle", "ALTER TABLE users ADD (age NUMBER NOT NULL);", ["add-not-null-no-default"]),
        ("sqlite", "ALTER TABLE users RENAME COLUMN a TO b;", ["rename-column"]),
        (
            "snowflake",
            "ALTER TABLE users ALTER COLUMN age SET DATA TYPE NUMBER(38,0);",
            ["alter-column-type"],
        ),
        ("db2", "ALTER TABLE users RENAME COLUMN a TO b;", ["statement-not-analysed"]),
    ],
)
def test_generic_rules(dialect, sql, expected):
    assert _codes(sql, dialect) == expected


@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            "CREATE INDEX idx ON users (email);",
            ["pg-index-not-concurrent", "pg-missing-lock-timeout"],
        ),
        ("CREATE INDEX CONCURRENTLY idx ON users (email);", []),
        (
            "ALTER TABLE o ADD CONSTRAINT fk FOREIGN KEY (uid) REFERENCES users (id);",
            ["pg-constraint-not-valid", "pg-missing-lock-timeout"],
        ),
        (
            "ALTER TABLE o ADD CONSTRAINT fk FOREIGN KEY (uid) REFERENCES users (id) NOT VALID;",
            ["pg-missing-lock-timeout"],
        ),
        (
            "ALTER TABLE o ADD CONSTRAINT ck CHECK (x > 0);",
            ["pg-constraint-not-valid", "pg-missing-lock-timeout"],
        ),
        (
            "ALTER TABLE users ALTER COLUMN age SET NOT NULL;",
            ["pg-missing-lock-timeout", "pg-set-not-null"],
        ),
        (
            "ALTER TABLE users ALTER COLUMN age TYPE BIGINT;",
            ["alter-column-type", "pg-missing-lock-timeout"],
        ),
        ("SET LOCAL lock_timeout = '5s';\nALTER TABLE users ADD COLUMN a INT;", []),
        (
            "ALTER TABLE users ADD COLUMN a INT;\nSET LOCAL lock_timeout = '5s';",
            ["pg-missing-lock-timeout"],
        ),
        (
            "CREATE TABLE t (id INT);\nCREATE INDEX i ON t (id);\nALTER TABLE t ADD COLUMN a INT NOT NULL;",
            [],
        ),
    ],
)
def test_postgresql_rules(sql, expected):
    assert sorted(_codes(sql, "postgresql")) == sorted(expected)


def test_postgresql_compound_alter_reports_drop_column():
    # sqlglot 30.18 cannot parse this form; 30.22 can and checks its table lock.
    assert set(_codes("ALTER TABLE users ADD COLUMN a INT, DROP COLUMN b;", "postgresql")) in (
        {"drop-column", "statement-not-analysed"},
        {"drop-column", "pg-missing-lock-timeout"},
    )


@pytest.mark.parametrize("dialect", ["cockroachdb", "redshift", "yugabytedb", "mysql"])
def test_lock_rules_stay_on_the_postgresql_list(dialect):
    assert _codes("CREATE INDEX idx ON users (email);", dialect) == []


@pytest.mark.parametrize(
    "dialect, expected",
    [
        ("postgresql", True),
        ("neon", True),
        ("supabase", True),
        ("aurora-postgresql", True),
        ("alloydb", True),
        ("timescaledb", True),
        ("citus", True),
        ("cockroachdb", False),
        ("redshift", False),
        ("yugabytedb", False),
        ("mysql", False),
        ("sqlite", False),
    ],
)
def test_postgresql_lock_rules_quirk_per_dialect(dialect, expected):
    assert ProviderRegistry.get_quirks(dialect).postgresql_lock_rules is expected


def test_mixed_transaction_modes_is_an_error():
    findings = find_issues(
        analyse_script(
            "SET LOCAL lock_timeout = '5s';\n"
            "CREATE INDEX CONCURRENTLY idx ON users (email);\n"
            "ALTER TABLE users ADD COLUMN a INT;",
            "postgresql",
        ),
        "postgresql",
    )
    mixed = [f for f in findings if f.code == "mixed-transaction-modes"]
    assert len(mixed) == 1 and mixed[0].severity == ERROR and mixed[0].statement == 1


def test_a_script_of_only_autocommit_statements_is_not_mixed():
    assert _codes("CREATE INDEX CONCURRENTLY idx ON users (email);", "postgresql") == []


def test_severities_are_fixed():
    assert SEVERITY["drop-table"] == ERROR
    assert SEVERITY["pg-missing-lock-timeout"] == WARNING
    assert SEVERITY["statement-not-analysed"] == INFO


def test_unparseable_statements_do_not_log_sqlglot_fallback_warnings(caplog):
    analysis = analyse_script("ALTER TABLE users ADD COLUMN a INT, DROP COLUMN b;", "postgresql")
    caplog.clear()  # the hybrid parser's own sqlglot pass is not under test here
    with caplog.at_level(logging.WARNING, logger="sqlglot"):
        find_issues(analysis, "postgresql")
    assert not [r for r in caplog.records if r.name.startswith("sqlglot")]


def test_finding_serialises():
    finding = find_issues(analyse_script("TRUNCATE users;", "mysql"), "mysql")[0]
    assert finding.to_dict() == {
        "code": "truncate",
        "severity": "error",
        "statement": 0,
        "message": finding.message,
        "snippet": "TRUNCATE users",
        "allowed": False,
    }
