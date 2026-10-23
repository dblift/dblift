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
        f'CREATE SEQUENCE, CREATE TYPE TO "{schema}"'
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
