"""``find_issues``: the rules ``validate-sql`` applies to one script."""

from __future__ import annotations

import logging

import pytest

from dblift.core.migration.sql.lint import lint_script
from dblift.core.migration.sql.lint_rules import ERROR, INFO, SEVERITY, WARNING, find_issues
from dblift.core.migration.sql.script_analysis import (
    AnalysedObject,
    AnalysedStatement,
    _caution_for,
    analyse_script,
)
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


def test_mixed_transaction_modes_names_the_statement_not_one_its_text_is_inside():
    findings = find_issues(
        analyse_script(
            "SELECT 1;\nCREATE INDEX CONCURRENTLY i2 ON t (a) -- SELECT 1\n;", "postgresql"
        ),
        "postgresql",
    )
    mixed = [f for f in findings if f.code == "mixed-transaction-modes"]
    assert [f.statement for f in mixed] == [1]


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
    # pg-missing-lock-timeout also needs sqlglot to parse a multi-table DROP (not on 30.0).
    assert "drop-table" in codes


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("CREATE TABLE t (id INT);\nDROP TABLE t;", ["drop-table"]),
        ("CREATE TABLE t (id INT);\nTRUNCATE TABLE t IMMEDIATE;", ["truncate"]),
    ],
)
def test_a_statement_the_parser_cannot_read_is_never_on_a_new_table(sql, expected):
    assert _codes(sql, "db2") == expected


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


def _quote(dialect: str, name: str) -> str:
    if dialect in ("mysql", "sqlite"):
        return f"`{name}`"
    if dialect == "sqlserver":
        return f"[{name}]"
    return f'"{name}"'


def _foreign(dialect: str, name: str) -> str:
    """*name* spelled the way the engine does not store an unquoted *name*."""
    return name.lower() if dialect == "oracle" else name.upper()


_QUOTING_DIALECTS = ["postgresql", "oracle", "mysql", "sqlserver", "sqlite"]


def _drops(dialect: str, create_name: str, drop_name: str):
    return _codes(f"CREATE TABLE {create_name} (id INT);\nDROP TABLE {drop_name};", dialect)


@pytest.mark.parametrize("dialect", _QUOTING_DIALECTS)
def test_a_quoted_drop_of_a_differently_cased_new_table_is_reported(dialect):
    assert "drop-table" in _drops(dialect, "t", _quote(dialect, _foreign(dialect, "t")))


@pytest.mark.parametrize("dialect", _QUOTING_DIALECTS)
def test_an_unquoted_drop_of_a_quoted_new_table_is_reported(dialect):
    assert "drop-table" in _drops(dialect, _quote(dialect, _foreign(dialect, "t")), "t")


@pytest.mark.parametrize("dialect", _QUOTING_DIALECTS)
def test_quoted_names_differing_in_case_do_not_match(dialect):
    assert "drop-table" in _drops(dialect, _quote(dialect, "t"), _quote(dialect, "T"))


@pytest.mark.parametrize("dialect", _QUOTING_DIALECTS)
@pytest.mark.parametrize("create_name, drop_name", [("t", "T"), ("T", "t"), ("t", "t")])
def test_unquoted_names_equal_ignoring_case_stay_exempt(dialect, create_name, drop_name):
    assert _drops(dialect, create_name, drop_name) == []


@pytest.mark.parametrize("dialect", _QUOTING_DIALECTS)
def test_byte_equal_quoted_names_stay_exempt(dialect):
    q = _quote(dialect, "T")
    assert _drops(dialect, q, q) == []


@pytest.mark.parametrize("dialect", _QUOTING_DIALECTS)
def test_quoting_of_the_schema_part_counts(dialect):
    create = (
        f"CREATE TABLE app.t (id INT);\nDROP TABLE {_quote(dialect, _foreign(dialect, 'app'))}.t;"
    )
    assert "drop-table" in _codes(create, dialect)
    same = (
        f"CREATE TABLE {_quote(dialect, 'APP')}.t (id INT);\nDROP TABLE {_quote(dialect, 'APP')}.t;"
    )
    assert _codes(same, dialect) == []


def test_quoting_survives_the_hand_over_between_scripts():
    created = lint_script("CREATE TABLE t (id INT);", "postgresql").created_tables
    assert "drop-table" in [
        f.code
        for f in lint_script('DROP TABLE "T";', "postgresql", created_before=created).findings
    ]
    quoted = lint_script('CREATE TABLE "a.b"."T" (id INT);', "postgresql").created_tables
    same = lint_script('DROP TABLE "a.b"."T";', "postgresql", created_before=quoted)
    assert [f.code for f in same.findings] == []
    other = lint_script('DROP TABLE "a.b"."t";', "postgresql", created_before=quoted)
    assert "drop-table" in [f.code for f in other.findings]


def test_a_known_existing_table_matches_whatever_the_quoting():
    analysis = analyse_script('CREATE TABLE "T" (a INT);\nDROP TABLE "T";', "postgresql")
    codes = [f.code for f in find_issues(analysis, "postgresql", existing_tables={"t"})]
    assert "drop-table" in codes


# A quoted name matches an unquoted one when spelled as the engine stores the unquoted one.
_STORED = [
    ("postgresql", "users", "Users"),
    ("oracle", "USERS", "users"),
    ("mysql", "users", "Users"),
    ("sqlserver", "users", "Users"),
    ("sqlite", "users", "Users"),
]


@pytest.mark.parametrize("dialect, stored, other", _STORED)
def test_a_quoted_name_spelled_as_the_engine_stores_it_matches_the_unquoted_one(
    dialect, stored, other
):
    assert _drops(dialect, _quote(dialect, stored), "users") == []
    assert _drops(dialect, "users", _quote(dialect, stored)) == []
    assert (
        _codes(f"CREATE TABLE {_quote(dialect, stored)}.t (id INT);\nDROP TABLE users.t;", dialect)
        == []
    )


@pytest.mark.parametrize("dialect, stored, other", _STORED)
def test_a_quoted_name_spelled_otherwise_does_not_match_the_unquoted_one(dialect, stored, other):
    assert "drop-table" in _drops(dialect, _quote(dialect, other), "users")
    assert "drop-table" in _drops(dialect, "users", _quote(dialect, other))
    assert "drop-table" in _codes(
        f"CREATE TABLE {_quote(dialect, other)}.t (id INT);\nDROP TABLE users.t;", dialect
    )


@pytest.mark.parametrize("dialect", _QUOTING_DIALECTS)
@pytest.mark.parametrize(
    "create_name", ["users", "Users", "USERS", '"users"', '"Users"', '"USERS"']
)
@pytest.mark.parametrize("drop_name", ["users", "Users", "USERS", '"users"', '"Users"', '"USERS"'])
def test_the_exemption_is_never_wider_than_folding_every_name(dialect, create_name, drop_name):
    if _drops(dialect, create_name, drop_name) == []:
        assert create_name.strip('"').lower() == drop_name.strip('"').lower()


@pytest.mark.parametrize("text", ["", "."])
def test_an_empty_created_table_name_is_not_an_error(text):
    analysis = analyse_script("DROP TABLE t;", "postgresql")
    assert "drop-table" in [
        f.code for f in find_issues(analysis, "postgresql", created_before={text})
    ]


def test_a_doubled_quote_in_a_name_survives_the_hand_over():
    created = lint_script('CREATE TABLE "a""b" (id INT);', "postgresql").created_tables
    same = lint_script('DROP TABLE "a""b";', "postgresql", created_before=created)
    assert [f.code for f in same.findings] == []
    for other in ('DROP TABLE "a";', 'DROP TABLE "a""";', 'DROP TABLE "ab";'):
        got = lint_script(other, "postgresql", created_before=created)
        assert "drop-table" in [f.code for f in got.findings], other


@pytest.mark.parametrize(
    "sql",
    [
        "DROP STAGE st;",
        "DROP TAG t;",
        "DROP FILE FORMAT ff;",
    ],
)
def test_a_drop_of_an_object_that_could_not_be_read_asks_for_a_review(sql):
    result = lint_script(sql, "snowflake")

    assert [f.code for f in result.findings] == ["drop-unread-object"]
    assert result.verdict == "REVIEW"


@pytest.mark.parametrize(
    "sql",
    [
        "DROP SEQUENCE q;",
        "DROP VIEW v;",
        "DROP FUNCTION f(int);",
        "DROP TRIGGER trg;",
        "DROP USER u;",
    ],
)
def test_a_drop_of_a_named_object_that_holds_no_rows_stays_safe(sql):
    assert lint_script(sql, "snowflake").verdict == "SAFE"


def test_the_unread_drop_rule_is_a_warning():
    assert SEVERITY["drop-unread-object"] == WARNING


# Each kind below is documented by its vendor as removing a definition, not rows: PostgreSQL
# sql-drop{policy,rule,publication,server,collation,cast,aggregate,language}, MySQL drop-event and
# drop-server, Oracle DROP SYNONYM / PACKAGE / DIRECTORY / PROFILE, SQL Server DROP LOGIN /
# SYNONYM / DEFAULT / RULE / ASSEMBLY, DuckDB DROP (macro), Db2 DROP (nickname: "the data source
# table ... is not affected"), Redshift DROP LIBRARY / GROUP.
@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("postgresql", "DROP POLICY p ON t;"),
        ("postgresql", "DROP RULE r ON t;"),
        ("postgresql", "DROP PUBLICATION pub;"),
        ("postgresql", "DROP SERVER s;"),
        ("postgresql", "DROP COLLATION c;"),
        ("postgresql", "DROP CAST (int AS text);"),
        ("postgresql", "DROP AGGREGATE a(int);"),
        ("postgresql", "DROP LANGUAGE plx;"),
        ("mysql", "DROP EVENT e;"),
        ("mysql", "DROP SERVER s;"),
        ("oracle", "DROP SYNONYM s;"),
        ("oracle", "DROP PUBLIC SYNONYM s;"),
        ("oracle", "DROP PACKAGE p;"),
        ("oracle", "DROP PACKAGE BODY p;"),
        ("oracle", "DROP DIRECTORY d;"),
        ("oracle", "DROP PROFILE p;"),
        ("sqlserver", "DROP LOGIN l;"),
        ("sqlserver", "DROP SYNONYM s;"),
        ("sqlserver", "DROP DEFAULT d;"),
        ("sqlserver", "DROP RULE r;"),
        ("sqlserver", "DROP ASSEMBLY a;"),
        ("duckdb", "DROP MACRO m;"),
        ("db2", "DROP NICKNAME n;"),
        ("redshift", "DROP LIBRARY l;"),
        ("redshift", "DROP GROUP g;"),
    ],
)
def test_a_drop_of_a_kind_that_holds_no_rows_stays_safe_when_unread(dialect, sql):
    assert lint_script(sql, dialect).verdict == "SAFE"


@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("postgresql", "DROP SUBSCRIPTION sub;"),
        ("postgresql", "DROP TABLESPACE ts;"),
        ("postgresql", "DROP COLLATION c CASCADE;"),
        ("oracle", "DROP SYNONYM s FORCE;"),
        ("sqlserver", "DROP CERTIFICATE c;"),
        ("duckdb", "DROP SECRET s;"),
        ("snowflake", "DROP STAGE st;"),
        ("postgresql", "DROP;"),
        ("snowflake", "DROP EVENT TABLE e;"),
        ("snowflake", 'DROP EVENT TABLE IF EXISTS "S"."APP_EVENTS";'),
        ("postgresql", "DROP EXTENSION pg_cron;"),
    ],
)
def test_a_drop_that_may_lose_data_or_cannot_be_classified_asks_for_a_review(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW"
    assert [f.code for f in result.findings] == ["drop-unread-object"]


# Db2 DROP TABLESPACE drops the tables that live in it with their rows (measured on Db2 12.1.5.0,
# 2026-10-24: the table was gone and SELECT from it was SQL0204N), so the table space the reader
# names is judged as the tables it takes with it. DROP BUFFERPOOL and DROP STOGROUP fail while a
# table space uses them (SQL0478N), and DROP MODULE removes definitions, not rows.
def test_a_named_db2_table_space_drop_is_judged_as_a_table_drop():
    result = lint_script("DROP TABLESPACE ts;", "db2")

    assert [f.code for f in result.findings] == ["drop-table"]
    assert result.verdict == lint_script("DROP TABLE t;", "db2").verdict


def _named_tablespace_drop():
    return AnalysedStatement(
        0,
        "DROP",
        "DDL",
        (AnalysedObject("TABLESPACE", "TS", None),),
        False,
        "DROP TABLESPACE ts",
    )


# PostgreSQL and MySQL refuse to drop a table space that still holds tables, so a dialect whose
# quirks do not list TABLESPACE among the types that discard rows does not report the drop as one.
def test_a_named_table_space_drop_discards_rows_only_where_the_dialect_says_so():
    stmt = _named_tablespace_drop()

    assert _caution_for(stmt, "DROP TABLESPACE ts", frozenset()) is None
    caution = _caution_for(stmt, "DROP TABLESPACE ts", frozenset({"TABLESPACE"}))
    assert caution is not None and caution.code == "drop-table"


@pytest.mark.parametrize(
    "sql", ["DROP BUFFERPOOL b;", "DROP STOGROUP sg;", "DROP MODULE m;", "DROP TYPE t;"]
)
def test_a_named_db2_drop_that_holds_no_rows_is_safe(sql):
    assert lint_script(sql, "db2").verdict == "SAFE"


# A database link and a materialized view log are definitions: Oracle's DROP DATABASE LINK removes
# the link, DROP MATERIALIZED VIEW LOG removes the change log of a master table, not its rows.
# Neither is a DROP DATABASE / DROP MATERIALIZED VIEW, which the keyword match used to take them for.
@pytest.mark.parametrize(
    "sql",
    [
        "DROP DATABASE LINK l1;",
        "DROP PUBLIC DATABASE LINK l1;",
        "DROP MATERIALIZED VIEW LOG ON emp;",
    ],
)
def test_dropping_a_link_or_a_materialized_view_log_is_not_dropping_a_database_or_table(sql):
    result = lint_script(sql, "oracle")

    assert result.verdict == "SAFE"
    assert not result.findings


@pytest.mark.parametrize(
    "sql, code",
    [
        ("DROP DATABASE d;", "drop-schema"),
        ("DROP MATERIALIZED VIEW mv1;", "drop-table"),
    ],
)
def test_dropping_a_database_or_a_materialized_view_stays_unsafe(sql, code):
    result = lint_script(sql, "oracle")

    assert result.verdict == "UNSAFE"
    assert [f.code for f in result.findings] == [code]


# Names that merely begin with LINK or LOG are not the LINK / LOG keywords. Db2 cannot name these
# statements' objects, so the keyword match alone decides: a prefix test (`L`) would read them as links.
@pytest.mark.parametrize(
    "sql, code",
    [
        ("DROP DATABASE linkdb;", "drop-schema"),
        ("DROP MATERIALIZED VIEW logx;", "drop-table"),
    ],
)
def test_a_name_starting_with_link_or_log_is_still_a_database_or_materialized_view(sql, code):
    result = lint_script(sql, "db2")

    assert result.verdict == "UNSAFE"
    assert [f.code for f in result.findings] == [code]


# LOCK TABLE and VACUUM FULL take a lock on a table (PostgreSQL docs, explicit-locking and sql-vacuum:
# the default LOCK mode and VACUUM FULL are ACCESS EXCLUSIVE). A waiting SHARE or stronger request
# blocks later writes (ROW EXCLUSIVE conflicts with SHARE); ACCESS SHARE, ROW SHARE, ROW EXCLUSIVE
# and SHARE UPDATE EXCLUSIVE leave ordinary reads and writes running, and NOWAIT never queues.
@pytest.mark.parametrize(
    "sql",
    [
        "LOCK TABLE a IN ACCESS EXCLUSIVE MODE;",
        "LOCK a;",
        "LOCK TABLE a;",
        "LOCK TABLE ONLY a, b;",
        "lock table a in share mode;",
        "LOCK TABLE a IN SHARE ROW EXCLUSIVE MODE;",
        "LOCK TABLE a IN EXCLUSIVE MODE;",
        "VACUUM FULL a;",
        "VACUUM FULL;",
        "VACUUM FULL VERBOSE a;",
        "VACUUM VERBOSE FULL a;",
        "VACUUM (FULL) a;",
        "VACUUM (FULL, ANALYZE) a;",
        "VACUUM (ANALYZE, FULL true) a;",
        "VACUUM (FULL ON) a;",
    ],
)
def test_lock_table_and_vacuum_full_need_a_lock_timeout(sql):
    assert _codes(sql, "postgresql") == ["pg-missing-lock-timeout"]


@pytest.mark.parametrize(
    "sql",
    [
        "LOCK TABLE a IN ACCESS SHARE MODE;",
        "LOCK TABLE a IN ROW SHARE MODE;",
        "LOCK TABLE a IN ROW EXCLUSIVE MODE;",
        "LOCK TABLE a IN SHARE UPDATE EXCLUSIVE MODE;",
        "LOCK TABLE a IN ACCESS EXCLUSIVE MODE NOWAIT;",
        "VACUUM a;",
        "VACUUM;",
        "VACUUM ANALYZE a;",
        "VACUUM (ANALYZE) a;",
        "VACUUM (FULL false) a;",
        "VACUUM (FULL off, ANALYZE) a;",
        "SET lock_timeout = '5s';\nLOCK TABLE a IN ACCESS EXCLUSIVE MODE;",
    ],
)
def test_weaker_locks_and_a_set_lock_timeout_are_not_reported(sql):
    assert _codes(sql, "postgresql") == []


def test_vacuum_full_after_a_set_lock_timeout_is_not_reported():
    # VACUUM cannot run in a transaction block, so this script is also a mixed-mode script.
    codes = _codes("SET lock_timeout = '5s';\nVACUUM FULL a;", "postgresql")

    assert "pg-missing-lock-timeout" not in codes


def test_the_lock_timeout_is_reported_once_across_lock_statements():
    sql = "LOCK TABLE a;\nVACUUM FULL b;\nALTER TABLE c ADD COLUMN d INT;"

    assert _codes(sql, "postgresql").count("pg-missing-lock-timeout") == 1


def test_lock_statements_of_other_dialects_are_not_postgresql_lock_findings():
    assert _codes("LOCK TABLES a WRITE;", "mysql") == []


# A table created earlier in the script has no readers or writers to queue behind, so locking it
# (LOCK TABLE, VACUUM FULL) needs no lock_timeout, as for ALTER TABLE on it.
@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE n (id int); LOCK TABLE n IN ACCESS EXCLUSIVE MODE;",
        "CREATE TABLE n (id int); LOCK n;",
        "CREATE TABLE n (id int); LOCK TABLE ONLY n;",
        "CREATE TABLE n (id int); VACUUM FULL n;",
        "CREATE TABLE n (id int); VACUUM (FULL) n;",
        "CREATE TABLE n (id int); CREATE TABLE m (id int); LOCK TABLE n, m;",
    ],
)
def test_locking_a_table_created_earlier_in_the_script_is_not_reported(sql):
    assert "pg-missing-lock-timeout" not in _codes(sql, "postgresql")


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE n (id int); LOCK TABLE n, old_t;",
        "CREATE TABLE n (id int); LOCK TABLE old_t;",
        "CREATE TABLE n (id int); VACUUM FULL old_t;",
        "CREATE TABLE n (id int); VACUUM FULL;",
    ],
)
def test_locking_a_table_not_created_in_the_script_is_still_reported(sql):
    # VACUUM cannot run in a transaction block, so it may add a mixed-mode finding.
    assert "pg-missing-lock-timeout" in _codes(sql, "postgresql")


@pytest.mark.parametrize(
    "sql",
    [
        "LOCK TABLE a IN ACCESS EXCLUSIVE MODE NOWAIT; -- x",
        "LOCK TABLE a IN ACCESS EXCLUSIVE MODE NOWAIT /* c */;",
        "LOCK TABLE a IN ACCESS EXCLUSIVE MODE NOWAIT -- x",
    ],
)
def test_a_comment_after_nowait_does_not_hide_it(sql):
    assert _codes(sql, "postgresql") == []
