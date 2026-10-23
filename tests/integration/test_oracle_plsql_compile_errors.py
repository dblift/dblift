"""Live check: a PL/SQL unit that Oracle compiles with errors fails the migration.

Oracle answers ``CREATE PROCEDURE`` / ``CREATE TRIGGER`` whose body does not
compile with "success with compilation error" (ORA-24344): no exception, the
object is left INVALID and the errors sit in ``USER_ERRORS``. An INVALID
trigger then fails every DML on its table, so these tests assert the state a
real ``migrate()`` leaves behind, not that a method was called.

Requires Oracle on localhost:1521 (service FREEPDB1, ``system`` / ``oracle``);
the fixture provisions its own schema owner and drops it afterwards.
"""

import uuid
from pathlib import Path
from typing import Any, Iterator, List, Tuple

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.oracle.config import OracleConfig
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider
from tests.integration.helpers.migration_helper import create_versioned_migration

pytestmark = [pytest.mark.integration, pytest.mark.oracle]

OWNER_PASSWORD = "Fix0plsql1"


def _config(username: str, password: str, schema: str) -> DbliftConfig:
    return DbliftConfig(
        database=OracleConfig(
            type="oracle",
            host="localhost",
            port=1521,
            service_name="FREEPDB1",
            username=username,
            password=password,
            schema=schema,
        )
    )


@pytest.fixture
def owner() -> Iterator[Tuple[Any, str]]:
    admin = ProviderRegistry.create_provider(_config("system", "oracle", "SYSTEM"))
    admin.create_connection()
    schema = f"FIX_PLSQL_{uuid.uuid4().hex[:8].upper()}"
    admin.execute_statement(f'CREATE USER "{schema}" IDENTIFIED BY "{OWNER_PASSWORD}"')
    admin.execute_statement(f'ALTER USER "{schema}" QUOTA UNLIMITED ON USERS')
    admin.execute_statement(
        f"GRANT CREATE SESSION, CREATE TABLE, CREATE PROCEDURE, CREATE TRIGGER, "
        f'CREATE SEQUENCE, CREATE TYPE, CREATE VIEW TO "{schema}"'
    )
    try:
        yield admin, schema
    finally:
        admin.execute_statement(f'DROP USER "{schema}" CASCADE')
        admin.close()


def _migrate(schema: str, migrations_dir: Path) -> Any:
    config = _config(schema, OWNER_PASSWORD, schema)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
    try:
        return client.migrate()
    finally:
        provider.close()


def _rows(admin: Any, schema: str, table: str) -> int:
    rows = admin.execute_query(f'SELECT COUNT(*) AS n FROM "{schema}".{table}')
    return int(rows[0].get("n", rows[0].get("N")))


def _status(admin: Any, schema: str, name: str) -> List[str]:
    rows = admin.execute_query(
        "SELECT status FROM all_objects WHERE owner = ? AND object_name = ?", [schema, name]
    )
    return [r.get("status", r.get("STATUS")) for r in rows]


def _history(admin: Any, schema: str) -> List[Tuple[str, bool]]:
    rows = sorted(admin.get_applied_migrations(schema), key=lambda r: r["installed_rank"])
    return [(r["script"], r["success"]) for r in rows]


def _write(migrations_dir: Path, version: str, description: str, sql: str) -> None:
    create_versioned_migration(migrations_dir, version, description, sql)


TABLE = "CREATE TABLE emp (id NUMBER, name VARCHAR2(20));\n"

BAD_TRIGGER = (
    "CREATE OR REPLACE TRIGGER bad_trg BEFORE INSERT ON emp FOR EACH ROW\n"
    "BEGIN\n  :NEW.nope_col := 1;\nEND;\n/\n"
)
BAD_PROCEDURE = "CREATE OR REPLACE PROCEDURE bad_p AS\nBEGIN\n  no_such_proc(1);\nEND;\n/\n"
GOOD_PROCEDURE = "CREATE OR REPLACE PROCEDURE good_p AS\nBEGIN\n  NULL;\nEND;\n/\n"


@pytest.mark.parametrize(
    ("sql", "object_name"),
    [(BAD_PROCEDURE, "BAD_P"), (BAD_TRIGGER, "BAD_TRG")],
    ids=["procedure", "trigger"],
)
def test_unit_with_compile_errors_fails_the_migration(owner, tmp_path, sql, object_name) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "emp", TABLE)
    _write(tmp_path, "2.0.0", "unit", sql)

    result = _migrate(schema, tmp_path)

    assert not result.success
    assert object_name in (result.error_message or "").upper()
    assert "PLS-" in (result.error_message or "")
    assert _history(admin, schema) == [("V1_0_0__emp.sql", True), ("V2_0_0__unit.sql", False)]


def test_valid_unit_still_succeeds(owner, tmp_path) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "emp", TABLE)
    _write(tmp_path, "2.0.0", "unit", GOOD_PROCEDURE)

    result = _migrate(schema, tmp_path)

    assert result.success, result.error_message
    assert _status(admin, schema, "GOOD_P") == ["VALID"]


def test_replacing_an_invalid_unit_with_a_fixed_body_succeeds(owner, tmp_path) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "emp", TABLE)
    # Bypass the Oracle provider's own check: this unit is deliberately left INVALID.
    SqlAlchemyProvider.execute_statement(
        admin, f'CREATE OR REPLACE PROCEDURE "{schema}".bad_p AS BEGIN no_such_proc(1); END;'
    )
    assert _status(admin, schema, "BAD_P") == ["INVALID"]
    _write(
        tmp_path,
        "2.0.0",
        "fix",
        "CREATE OR REPLACE PROCEDURE bad_p AS\nBEGIN\n  NULL;\nEND;\n/\n",
    )

    result = _migrate(schema, tmp_path)

    assert result.success, result.error_message
    assert _status(admin, schema, "BAD_P") == ["VALID"]


# --- the verdict waits for the end of the migration ------------------------------------------------

FORWARD_REFERENCE = (
    "CREATE OR REPLACE PROCEDURE a_p AS\nBEGIN\n  b_p;\nEND;\n/\n"
    "CREATE OR REPLACE PROCEDURE b_p AS\nBEGIN\n  NULL;\nEND;\n/\n"
)

MUTUAL_PACKAGES = (
    "CREATE OR REPLACE PACKAGE pk_a AS\n  FUNCTION f RETURN NUMBER;\nEND;\n/\n"
    "CREATE OR REPLACE PACKAGE pk_b AS\n  FUNCTION f RETURN NUMBER;\nEND;\n/\n"
    "CREATE OR REPLACE PACKAGE BODY pk_a AS\n"
    "  FUNCTION f RETURN NUMBER IS\n  BEGIN\n    RETURN 1;\n  END;\n"
    "  PROCEDURE g IS\n    n NUMBER := pk_b.f;\n  BEGIN\n    NULL;\n  END;\nEND;\n/\n"
    "CREATE OR REPLACE PACKAGE BODY pk_b AS\n"
    "  FUNCTION f RETURN NUMBER IS\n  BEGIN\n    RETURN pk_a.f;\n  END;\nEND;\n/\n"
)


def test_forward_reference_inside_one_migration_succeeds(owner, tmp_path) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "unit", FORWARD_REFERENCE)

    result = _migrate(schema, tmp_path)

    print(
        "forward:",
        result.success,
        _history(admin, schema),
        _status(admin, schema, "A_P"),
        _status(admin, schema, "B_P"),
    )
    assert result.success, result.error_message
    assert _history(admin, schema) == [("V1_0_0__unit.sql", True)]
    assert _status(admin, schema, "A_P") == ["VALID"]
    assert _status(admin, schema, "B_P") == ["VALID"]


def test_mutually_dependent_package_bodies_succeed(owner, tmp_path) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "pkgs", MUTUAL_PACKAGES)

    result = _migrate(schema, tmp_path)

    print(
        "mutual:",
        result.success,
        _history(admin, schema),
        _status(admin, schema, "PK_A"),
        _status(admin, schema, "PK_B"),
    )
    assert result.success, result.error_message
    assert _status(admin, schema, "PK_A") == ["VALID", "VALID"]
    assert _status(admin, schema, "PK_B") == ["VALID", "VALID"]


def test_unit_that_stays_broken_after_the_whole_file_names_the_unit(owner, tmp_path) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "unit", FORWARD_REFERENCE + BAD_PROCEDURE)

    result = _migrate(schema, tmp_path)

    print(
        "broken:",
        result.success,
        _history(admin, schema),
        _status(admin, schema, "A_P"),
        _status(admin, schema, "BAD_P"),
    )
    print((result.error_message or "").splitlines()[:4])
    assert not result.success
    message = result.error_message or ""
    assert "BAD_P" in message.upper() and "PLS-" in message
    assert "A_P" not in message.upper().replace("BAD_P", "")
    assert _history(admin, schema) == [("V1_0_0__unit.sql", False)]
    assert _status(admin, schema, "A_P") == ["VALID"]
    assert _status(admin, schema, "BAD_P") == ["INVALID"]


def test_alter_compile_with_errors_fails_the_migration(owner, tmp_path) -> None:
    admin, schema = owner
    _write(
        tmp_path,
        "1.0.0",
        "unit",
        TABLE
        + "CREATE OR REPLACE PROCEDURE ac AS\nBEGIN\n  INSERT INTO emp (id) VALUES (1);\nEND;\n/\n",
    )
    _write(tmp_path, "2.0.0", "break", "DROP TABLE emp;\nALTER PROCEDURE ac COMPILE;\n")

    result = _migrate(schema, tmp_path)

    print("alter-fails:", result.success, _history(admin, schema), _status(admin, schema, "AC"))
    print((result.error_message or "").splitlines()[:4])
    assert not result.success
    assert "AC" in (result.error_message or "").upper()
    assert _history(admin, schema)[-1] == ("V2_0_0__break.sql", False)
    assert _status(admin, schema, "AC") == ["INVALID"]


def test_alter_compile_that_fixes_a_unit_succeeds(owner, tmp_path) -> None:
    admin, schema = owner
    # Left INVALID on purpose: its table does not exist yet.
    SqlAlchemyProvider.execute_statement(
        admin,
        f'CREATE OR REPLACE PROCEDURE "{schema}".ac AS BEGIN INSERT INTO emp (id) VALUES (1); END;',
    )
    assert _status(admin, schema, "AC") == ["INVALID"]
    _write(tmp_path, "1.0.0", "fix", TABLE + "ALTER PROCEDURE ac COMPILE;\n")

    result = _migrate(schema, tmp_path)

    print("alter-fixes:", result.success, _history(admin, schema), _status(admin, schema, "AC"))
    assert result.success, result.error_message
    assert _status(admin, schema, "AC") == ["VALID"]


# --- the end-of-migration check is not a commit, and covers what a later statement invalidates ------


def test_a_failing_end_check_does_not_commit_the_migrations_dml(owner, tmp_path) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "unit", TABLE + BAD_PROCEDURE + "INSERT INTO emp (id) VALUES (1);\n")

    result = _migrate(schema, tmp_path)

    rows = _rows(admin, schema, "emp")
    print("dml-fails:", result.success, _history(admin, schema), "rows:", rows)
    assert not result.success
    assert rows == 0


def test_a_passing_end_check_commits_the_migrations_dml(owner, tmp_path) -> None:
    admin, schema = owner
    _write(
        tmp_path, "1.0.0", "unit", TABLE + FORWARD_REFERENCE + "INSERT INTO emp (id) VALUES (1);\n"
    )

    result = _migrate(schema, tmp_path)

    rows = _rows(admin, schema, "emp")
    print("dml-passes:", result.success, _history(admin, schema), "rows:", rows)
    assert result.success, result.error_message
    assert rows == 1


def test_a_trigger_invalidated_by_a_later_statement_fails_the_migration(owner, tmp_path) -> None:
    admin, schema = owner
    sql = (
        "CREATE TABLE e (id NUMBER, c NUMBER);\n"
        "CREATE OR REPLACE TRIGGER tt BEFORE INSERT ON e FOR EACH ROW\n"
        "BEGIN\n  :NEW.c := 1;\nEND;\n/\n"
        "ALTER TABLE e DROP COLUMN c;\n"
    )
    _write(tmp_path, "1.0.0", "unit", sql)

    result = _migrate(schema, tmp_path)

    print("trigger:", result.success, _history(admin, schema), _status(admin, schema, "TT"))
    print((result.error_message or "").splitlines()[:3])
    assert not result.success
    assert "TRIGGER TT" in (result.error_message or "")
    assert _status(admin, schema, "TT") == ["INVALID"]


def test_a_force_view_over_a_missing_table_fails_the_migration(owner, tmp_path) -> None:
    admin, schema = owner
    _write(tmp_path, "1.0.0", "unit", "CREATE OR REPLACE FORCE VIEW v AS SELECT * FROM missing;\n")

    result = _migrate(schema, tmp_path)

    print("view:", result.success, _history(admin, schema), _status(admin, schema, "V"))
    print((result.error_message or "").splitlines()[:3])
    assert not result.success
    assert "VIEW V" in (result.error_message or "")
    assert _history(admin, schema) == [("V1_0_0__unit.sql", False)]


def test_an_error_of_the_end_check_itself_is_recorded_as_a_failed_migration(
    owner, tmp_path
) -> None:
    admin, schema = owner
    other = f"{schema}_O"
    admin.execute_statement(f'CREATE USER "{other}" IDENTIFIED BY "{OWNER_PASSWORD}"')
    admin.execute_statement(f'GRANT CREATE SESSION TO "{other}"')
    admin.execute_statement(f'GRANT CREATE ANY PROCEDURE TO "{schema}"')
    try:
        _write(
            tmp_path,
            "1.0.0",
            "unit",
            f'CREATE OR REPLACE PROCEDURE "{other}".bad_o AS\nBEGIN\n  no_such_proc(1);\nEND;\n/\n',
        )

        result = _migrate(schema, tmp_path)

        print("hook-error:", result.success, _history(admin, schema))
        print((result.error_message or "").splitlines()[:3])
        assert not result.success
        assert _history(admin, schema) == [("V1_0_0__unit.sql", False)]
    finally:
        admin.execute_statement(f'DROP USER "{other}" CASCADE')
