"""A failing statement's literals stay out of every log format and result payload.

Runs the real CLI at DEBUG level, writing the text, JSON and HTML logs, and looks at the console,
the logs, ``migrate --format json`` and ``info --format json``. SQLite always runs. PostgreSQL and
MySQL run when ``DBLIFT_TEST_POSTGRES_URL`` / ``DBLIFT_TEST_MYSQL_URL`` point at a throwaway server
(the database or schema is dropped and recreated for every case).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_DBLIFT = str(Path(sys.executable).parent / "dblift")
S = "SECRET-LITERAL-42"

# Each case: (migration SQL, failing statement number, text that must not appear). The literal
# S is supplied only by the failing statement itself; statements that succeed are stored as written.

# --- SQLite -------------------------------------------------------------------------------------
_CHECK = "failed: c <> 'forbidden'"
_SQLITE_TABLE = (
    "CREATE TABLE t (id INTEGER PRIMARY KEY, c TEXT CHECK (c <> 'forbidden'), u TEXT UNIQUE);\n"
)
SQLITE = {
    "syntax-newline-in-value": (
        _SQLITE_TABLE + f"INSERT INTO t VALUES (1, 'x\n{S}' 'y', 'u');\n",
        2,
        S,
    ),
    "syntax-at-literal": (_SQLITE_TABLE + f"INSERT INTO t VALUES (1, 'a' '{S}', 'u');\n", 2, S),
    "check": (_SQLITE_TABLE + "INSERT INTO t VALUES (1, 'forbidden', 'u');\n", 2, _CHECK),
    "check-multi-row": (
        _SQLITE_TABLE + "INSERT INTO t VALUES (1, 'ok', 'a'), (2, 'forbidden', 'b');\n",
        2,
        _CHECK,
    ),
    "check-update": (
        _SQLITE_TABLE + "INSERT INTO t VALUES (1, 'ok', 'a');\nUPDATE t SET c = 'forbidden';\n",
        3,
        _CHECK,
    ),
    "doubled-quote-syntax": (
        _SQLITE_TABLE + f"INSERT INTO t VALUES (1, 'it''s {S}' 'x', 'u');\n",
        2,
        S,
    ),
    "unique-multi-row": (
        _SQLITE_TABLE + f"INSERT INTO t VALUES (1, 'a', '{S}'), (2, 'b', '{S}');\n",
        2,
        S,
    ),
}

# --- PostgreSQL ---------------------------------------------------------------------------------
_PG_TABLE = (
    "CREATE TABLE p (id INTEGER PRIMARY KEY, name TEXT UNIQUE, n INTEGER, "
    "CONSTRAINT p_chk CHECK (name <> 'forbidden'));\n"
    "CREATE TABLE c (id INTEGER, pname TEXT REFERENCES p (name));\n"
)
PG = {
    "cast-embedded-double-quote": (
        _PG_TABLE + "INSERT INTO p VALUES (1, 'a', 'SEC\"RET-LITERAL-42'::int);\n",
        3,
        "RET-LITERAL-42",
    ),
    "unique-newline-in-value": (
        _PG_TABLE + f"INSERT INTO p VALUES (1, 'x\n{S}', 1), (2, 'x\n{S}', 2);\n",
        3,
        S,
    ),
    "unique-multi-row": (_PG_TABLE + f"INSERT INTO p VALUES (1, '{S}', 1), (2, '{S}', 2);\n", 3, S),
    "unique-update": (
        _PG_TABLE + f"INSERT INTO p VALUES (1, 'a', 1), (2, 'b', 2);\nUPDATE p SET name = '{S}';\n",
        4,
        S,
    ),
    "check": (_PG_TABLE + "INSERT INTO p VALUES (1, 'forbidden', 1);\n", 3, "forbidden)"),
    "foreign-key": (_PG_TABLE + f"INSERT INTO c VALUES (1, '{S}');\n", 3, S),
    "cast": (_PG_TABLE + f"INSERT INTO p VALUES (1, 'a', '{S}');\n", 3, S),
    "cast-dollar-quoted": (_PG_TABLE + f"INSERT INTO p VALUES (1, 'a', $${S}$$);\n", 3, S),
    "cast-escape-string": (_PG_TABLE + f"INSERT INTO p VALUES (1, 'a', E'{S}\\n');\n", 3, S),
    "syntax": (_PG_TABLE + f"INSERT INTO p VALUES (1, '{S}' 'x', 1);\n", 3, S),
    "doubled-quote": (
        _PG_TABLE + f"INSERT INTO p VALUES (1, 'it''s {S}', 1), (2, 'it''s {S}', 2);\n",
        3,
        S,
    ),
    "do-block": (
        _PG_TABLE + f"DO $$ BEGIN INSERT INTO p VALUES (1, '{S}', 1), (2, '{S}', 2); END $$;\n",
        3,
        S,
    ),
    "execute": (
        _PG_TABLE
        + f"DO $$ BEGIN EXECUTE 'INSERT INTO p VALUES (1, ''{S}'', 1), (2, ''{S}'', 2)'; END $$;\n",
        3,
        S,
    ),
}

# --- MySQL --------------------------------------------------------------------------------------
_MY_TABLE = "CREATE TABLE m (id INT PRIMARY KEY, name VARCHAR(80) UNIQUE, n INT NOT NULL);\n"
MYSQL = {
    "duplicate-newline-in-value": (
        _MY_TABLE + f"INSERT INTO m VALUES (1, 'x\n{S}', 1), (2, 'x\n{S}', 2);\n",
        2,
        S,
    ),
    "duplicate-entry": (_MY_TABLE + f"INSERT INTO m VALUES (1, '{S}', 1), (2, '{S}', 2);\n", 2, S),
    "backslash-escape": (
        _MY_TABLE + f"INSERT INTO m VALUES (1, 'it\\'s {S}', 1), (2, 'it\\'s {S}', 2);\n",
        2,
        S,
    ),
    "incorrect-integer": (_MY_TABLE + f"INSERT INTO m VALUES (1, 'a', '{S}');\n", 2, S),
    "syntax-excerpt": (_MY_TABLE + f"INSERT INTO m VALUES (1, '{S}' 'x', 1, ;\n", 2, S),
    "long-syntax-excerpt": (
        _MY_TABLE + f"INSERT INTO m VALUES (1, '{S}', 1) {'x ' * 200} '{S}' ;\n",
        2,
        S,
    ),
}


def _cli(tmp_path, url, files, *args):
    mig = tmp_path / "mig"
    mig.mkdir(exist_ok=True)
    for name, sql in files.items():
        (mig / name).write_text(sql)
    (tmp_path / "d.yaml").write_text(f"database:\n  url: {url}\nmigrations:\n  directory: mig\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    env["HOME"] = str(tmp_path)
    return subprocess.run(
        [_DBLIFT, "--config", "d.yaml", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _check(tmp_path, url, files, expect, leak=S):
    failed = _cli(
        tmp_path,
        url,
        files,
        "--log-level",
        "debug",
        "--log-format",
        "text,json,html",
        "migrate",
        "--format",
        "json",
    )
    assert failed.returncode != 0, failed.stdout + failed.stderr
    info = _cli(tmp_path, url, files, "info", "--format", "json")
    logs = "".join(p.read_text() for p in (tmp_path / "logs").iterdir())
    everything = logs + failed.stdout + failed.stderr + info.stdout + info.stderr
    assert leak not in everything
    assert expect in everything


def _statement_marker(position):
    return f"Failed to execute statement {position}"


@pytest.mark.parametrize("case", SQLITE)
def test_sqlite(tmp_path, case):
    sql, position, leak = SQLITE[case]
    url = f"sqlite:///{tmp_path / 't.db'}"
    _check(tmp_path, url, {"V1__t.sql": sql}, _statement_marker(position), leak)


def test_sqlite_callback_error_is_masked(tmp_path):
    files = {
        "V1__t.sql": _SQLITE_TABLE,
        "beforeMigrate__bad.sql": f"INSERT INTO t VALUES (1, 'x' '{S}', 'u');\n",
    }
    _check(tmp_path, f"sqlite:///{tmp_path / 't.db'}", files, "beforeMigrate__bad.sql")


def test_sqlite_after_callback_error_is_masked(tmp_path):
    files = {
        "V1__t.sql": _SQLITE_TABLE,
        "afterMigrate__bad.sql": f"INSERT INTO t VALUES (1, 'x' '{S}', 'u');\n",
    }
    _check(tmp_path, f"sqlite:///{tmp_path / 't.db'}", files, "afterMigrate__bad.sql")


def _pg_reset(url):
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


@pytest.mark.skipif(not os.environ.get("DBLIFT_TEST_POSTGRES_URL"), reason="needs PostgreSQL")
@pytest.mark.parametrize("case", PG)
def test_postgresql(tmp_path, case):
    url = os.environ["DBLIFT_TEST_POSTGRES_URL"]
    _pg_reset(url)
    sql, position, leak = PG[case]
    _check(tmp_path, url, {"V1__t.sql": sql}, _statement_marker(position), leak)


@pytest.mark.skipif(not os.environ.get("DBLIFT_TEST_POSTGRES_URL"), reason="needs PostgreSQL")
def test_postgresql_callback_error_is_masked(tmp_path):
    url = os.environ["DBLIFT_TEST_POSTGRES_URL"]
    _pg_reset(url)
    files = {
        "V1__t.sql": _PG_TABLE,
        "beforeMigrate__bad.sql": f"INSERT INTO p VALUES (1, '{S}', 1), (2, '{S}', 2);\n",
    }
    _check(tmp_path, url, files, "beforeMigrate__bad.sql")


def _mysql_reset(url):
    from urllib.parse import urlparse

    import pymysql

    u = urlparse(url)
    conn = pymysql.connect(
        host=u.hostname, port=u.port, user=u.username, password=u.password, autocommit=True
    )
    db = u.path.lstrip("/")
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {db}")
    conn.cursor().execute(f"CREATE DATABASE {db}")
    conn.close()


@pytest.mark.skipif(not os.environ.get("DBLIFT_TEST_MYSQL_URL"), reason="needs MySQL")
@pytest.mark.parametrize("case", MYSQL)
def test_mysql(tmp_path, case):
    url = os.environ["DBLIFT_TEST_MYSQL_URL"]
    _mysql_reset(url)
    sql, position, leak = MYSQL[case]
    _check(tmp_path, url, {"V1__t.sql": sql}, _statement_marker(position), leak)


def test_failure_reports_the_json_error_with_position(tmp_path):
    url = f"sqlite:///{tmp_path / 't.db'}"
    out = _cli(tmp_path, url, {"V1__t.sql": SQLITE["check"][0]}, "migrate", "--format", "json")
    error = json.loads(out.stdout)["error"]
    assert error.startswith("Failed to execute statement 2 in V1__t.sql")
    assert "CHECK constraint failed" in error


def test_sqlite_error_callback_failure_is_masked(tmp_path):
    files = {
        "V1__t.sql": _SQLITE_TABLE + f"INSERT INTO t VALUES (1, 'a' '{S}', 'u');\n",
        "afterMigrateError__bad.sql": f"INSERT INTO t VALUES (1, 'x' '{S}', 'u');\n",
    }
    _check(tmp_path, f"sqlite:///{tmp_path / 't.db'}", files, "afterMigrateError__bad.sql")
