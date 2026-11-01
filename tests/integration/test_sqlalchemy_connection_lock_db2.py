"""``from_sqlalchemy(connection=...)`` on Db2 never waits on its own transaction.

The migration lock lives on a second connection, and Db2 DDL is transactional.
Each command below runs in a child process killed after ``TIMEOUT`` seconds, so
a regression fails the test instead of hanging the run (and the catalog locks
a hung session holds on the shared server).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import uuid

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration, pytest.mark.db2]

TIMEOUT = 45

_COMMAND = textwrap.dedent("""
    import os, sys
    from sqlalchemy import create_engine
    from dblift.api import DBLiftClient
    from dblift.core.logger import NullLog

    command, schema, migrations = sys.argv[1:4]
    engine = create_engine(os.environ["Q_DB2_URL"])
    with engine.connect() as conn:
        client = DBLiftClient.from_sqlalchemy(
            connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
        )
        result = getattr(client, command)()
        client.close()
    print("SUCCESS" if result.success else "FAILED: %s" % getattr(result, "error_message", ""))
    """)


def _url(config: dict) -> str:
    return (
        f"ibm_db_sa://{config['username']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )


def _run(command: str, url: str, schema: str, migrations) -> None:
    try:
        done = subprocess.run(
            [sys.executable, "-c", _COMMAND, command, schema, str(migrations)],
            env={**os.environ, "Q_DB2_URL": url},
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{command} on a caller-owned Db2 connection did not return in {TIMEOUT}s")
    assert "SUCCESS" in done.stdout, done.stdout + done.stderr


def _drop_schema(url: str, schema: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT 1 FROM SYSCAT.SCHEMATA WHERE SCHEMANAME = :s"), {"s": schema}
        ).first():
            return
        tables = conn.execute(
            text("SELECT TABNAME FROM SYSCAT.TABLES WHERE TABSCHEMA = :s"), {"s": schema}
        ).scalars()
        for table in tables.all():
            conn.execute(text(f'DROP TABLE "{schema}"."{table}"'))
        conn.execute(text(f'DROP SCHEMA "{schema}" RESTRICT'))
    engine.dispose()


def run_scenario(url: str, tmp_path) -> None:
    schema = f"Q_CONN_{uuid.uuid4().hex[:8].upper()}"
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__first.sql").write_text(
        f"CREATE TABLE T_{schema[-8:]}_1 (id INTEGER NOT NULL PRIMARY KEY);"
    )
    engine = create_engine(url)
    try:
        # The schema does not exist: dblift creates it, the history table and
        # the lock table, all through the caller's connection.
        _run("migrate", url, schema, migrations)
        (migrations / "V2__second.sql").write_text(
            f"CREATE TABLE T_{schema[-8:]}_2 (id INTEGER NOT NULL PRIMARY KEY);"
        )
        _run("info", url, schema, migrations)
        _run("validate", url, schema, migrations)
        # An initialised schema with a pending migration.
        _run("migrate", url, schema, migrations)
        with engine.connect() as conn:
            applied = (
                conn.execute(
                    text(
                        f'SELECT VERSION FROM "{schema}".DBLIFT_SCHEMA_HISTORY '
                        "WHERE SUCCESS = 1 ORDER BY INSTALLED_RANK"
                    )
                )
                .scalars()
                .all()
            )
        assert applied == ["1", "2"], applied
    finally:
        engine.dispose()
        _drop_schema(url, schema)


def test_caller_owned_connection_migrates_without_waiting_on_itself(db2_container, tmp_path):
    run_scenario(_url(db2_container), tmp_path)
