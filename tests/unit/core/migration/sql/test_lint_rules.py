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


@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("postgresql", "CREATE TABLE t (id INT);\nDROP TABLE t;"),
        ("postgresql", "CREATE TABLE t (id INT);\nTRUNCATE t;"),
        ("postgresql", "CREATE TABLE t (id INT, a INT);\nALTER TABLE t DROP COLUMN a;"),
        ("postgresql", "CREATE TABLE t (id INT);\nDELETE FROM t;"),
        ("postgresql", "CREATE TABLE t (id INT);\nUPDATE t SET id = 1;"),
        ("postgresql", "CREATE TABLE t (a INT);\nALTER TABLE t RENAME COLUMN a TO b;"),
        ("postgresql", "CREATE TABLE t (a INT);\nALTER TABLE t RENAME TO u;"),
        ("postgresql", "CREATE TABLE t (a INT);\nALTER TABLE t ALTER COLUMN a TYPE BIGINT;"),
        ("postgresql", "CREATE TABLE t (a INT);\nALTER TABLE t ALTER COLUMN a SET NOT NULL;"),
        ("postgresql", "CREATE TABLE t (a INT);\nTRUNCATE TABLE t;"),
        ("postgresql", "CREATE TABLE t AS SELECT 1 AS a;\nDROP TABLE t;"),
        ("postgresql", "CREATE TABLE app.T (a INT);\nDROP TABLE app.t;"),
        ("mysql", "CREATE TABLE t (a INT);\nALTER TABLE t MODIFY COLUMN a BIGINT;"),
        ("mysql", "CREATE TABLE t (a INT);\nDELETE FROM t;"),
    ],
)
def test_a_table_created_earlier_in_the_script_is_exempt(dialect, sql):
    assert _codes(sql, dialect) == []


def test_a_statement_before_the_create_is_still_reported():
    assert _codes("DROP TABLE t;\nCREATE TABLE t (id INT);", "mysql") == ["drop-table"]


def test_a_drop_of_a_new_and_an_existing_table_is_reported():
    codes = _codes("CREATE TABLE t (id INT);\nDROP TABLE t, users;", "postgresql")
    assert sorted(codes) == ["drop-table", "pg-missing-lock-timeout"]


def test_drop_schema_is_not_exempt():
    assert _codes("CREATE TABLE s (id INT);\nDROP SCHEMA s;", "mysql") == ["drop-schema"]


@pytest.mark.parametrize("name", ["t", "T", "app.t"])
def test_tables_created_before_the_script_are_exempt(name):
    analysis = analyse_script(f"DROP TABLE {name};\nCREATE INDEX i ON t (id);", "postgresql")
    assert find_issues(analysis, "postgresql", created_before={"t"}) == []


def test_tables_created_before_the_script_do_not_exempt_other_tables():
    analysis = analyse_script("CREATE INDEX i ON users (id);", "postgresql")
    codes = [f.code for f in find_issues(analysis, "postgresql", created_before={"t"})]
    assert codes == ["pg-index-not-concurrent", "pg-missing-lock-timeout"]


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("CREATE TABLE a.users (id INT);\nALTER TABLE users RENAME COLUMN id TO uid;", []),
        ("CREATE TABLE a.users (id INT);\nALTER TABLE a.users RENAME COLUMN id TO uid;", []),
        (
            "CREATE TABLE a.users (id INT);\nALTER TABLE b.users RENAME COLUMN id TO uid;",
            ["rename-column"],
        ),
        ("CREATE TABLE users (id INT);\nALTER TABLE x.users RENAME COLUMN id TO uid;", []),
        ("CREATE TABLE a.users (id INT);\nDROP TABLE a.users, b.users;", ["drop-table"]),
    ],
)
def test_created_tables_match_by_schema_when_both_name_one(sql, expected):
    assert _codes(sql, "mysql") == expected


def test_tables_created_before_match_by_schema():
    analysis = analyse_script("DROP TABLE b.users;", "mysql")
    codes = [f.code for f in find_issues(analysis, "mysql", created_before={"a.users"})]
    assert codes == ["drop-table"]


@pytest.mark.parametrize(
    "dialect, sql, expected",
    [
        (
            "postgresql",
            "CREATE TABLE IF NOT EXISTS t (a INT);\nCREATE INDEX i ON t (a);",
            ["pg-index-not-concurrent", "pg-missing-lock-timeout"],
        ),
        ("mysql", "CREATE TABLE IF NOT EXISTS tmp (a INT);\nDROP TABLE tmp;", ["drop-table"]),
        ("mysql", "CREATE TABLE IF NOT EXISTS t (a INT);\nTRUNCATE TABLE t;", ["truncate"]),
        ("mysql", "CREATE TABLE IF NOT EXISTS t AS SELECT 1 AS a;\nDROP TABLE t;", ["drop-table"]),
    ],
)
def test_create_table_if_not_exists_does_not_make_a_table_new(dialect, sql, expected):
    assert _codes(sql, dialect) == expected


def test_existing_tables_are_never_new():
    analysis = analyse_script("CREATE TABLE t (a INT);\nCREATE INDEX i ON t (a);", "postgresql")
    codes = [f.code for f in find_issues(analysis, "postgresql", existing_tables={"t"})]
    assert codes == ["pg-index-not-concurrent", "pg-missing-lock-timeout"]


@pytest.mark.parametrize("existing, expected", [({"a.t"}, []), ({"b.t"}, ["drop-table"])])
def test_existing_tables_match_by_schema(existing, expected):
    analysis = analyse_script("CREATE TABLE b.t (a INT);\nDROP TABLE b.t;", "mysql")
    codes = [f.code for f in find_issues(analysis, "mysql", existing_tables=existing)]
    assert codes == expected
