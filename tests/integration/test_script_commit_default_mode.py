"""Scripts that manage their own transaction, on every local engine.

dblift opens a transaction for each script, runs the statements, writes the
history row and commits. These tests run real scripts that commit, roll back,
open their own transaction or fail, and check three things after each run: the
reported outcome, the data and the history rows. Engines that report nothing
about the transaction a script ended keep the default: whatever follows the
script's COMMIT is committed with the history row, and a failure after that
COMMIT keeps the committed part.

Every scenario also asserts the truthfulness rule: ``result.success`` equals
the ``success`` of the last history row, a successful run has a history row
per migration, and a failed run leaves neither a row in ``h`` nor a changed
``t`` that the script did not commit itself.

They run against live PostgreSQL, MySQL, MariaDB and Oracle servers. Each test
provisions a throwaway database (Oracle: user) holding ``t (a, b)`` with the
row (1, 2) and an empty ``h (v)``, using an administrative account, and drops
it afterwards. An engine that cannot be reached is skipped; set
DBLIFT_<ENGINE>_HOST / _PORT / _USERNAME / _PASSWORD (PostgreSQL also
_DATABASE, Oracle also _SERVICE) to point at one. The Oracle service
defaults to FREEPDB1, like the other self-contained Oracle modules here.
An engine whose port answers but whose login fails is an error, not a skip.

Adding an engine is data: a provisioning branch, a row in DEFAULTS, a fragment
override in ENGINE_FRAGMENTS, and the engine's name in the rows it runs.
"""

import os
import socket
import uuid
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.db.plugins.cockroachdb.sqlalchemy_url import build_sqlalchemy_url
from dblift.db.plugins.mysql.config import MySqlConfig
from dblift.db.plugins.oracle.config import OracleConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_migration, create_undo_migration

pytestmark = pytest.mark.integration

ENGINES = ["postgresql", "mysql", "mariadb", "oracle", "cockroachdb"]
PG_FAMILY = ("postgresql", "cockroachdb")
ALL = ENGINES
DEFAULTS = {
    "postgresql": ("localhost", "5432", "postgres", "postgres"),
    "mysql": ("localhost", "3306", "root", "root"),
    "mariadb": ("localhost", "3306", "root", "root"),
    "oracle": ("localhost", "1521", "system", "oracle"),
    "cockroachdb": ("localhost", "26257", "root", ""),
}
DEFAULT_DATABASE = {"postgresql": "postgres", "cockroachdb": "defaultdb"}
ORACLE_USER_PASSWORD = "Dblift_Pin1x"

# Statement fragments. A scenario is a tuple of fragment names, joined by newlines.
FRAGMENTS = {
    "UPD": "UPDATE t SET a = b WHERE a = 1;",
    "INS1": "INSERT INTO h VALUES (1);",
    "INS2": "INSERT INTO h VALUES (2);",
    "INS7": "INSERT INTO h VALUES (7);",
    "FAIL": "INSERT INTO nosuch VALUES (1);",
    "COMMIT": "COMMIT;",
    "ROLLBACK": "ROLLBACK;",
    "SAVE": "SAVEPOINT s;",
    "BACK": "ROLLBACK TO SAVEPOINT s;",
    "UNDO_UPD": "UPDATE t SET a = 1 WHERE a = 2;",
}
MYSQL_PROCEDURE = (
    "DELIMITER //\n"
    "CREATE PROCEDURE p() BEGIN\n"
    "  UPDATE t SET a = b WHERE a = 1;\n"
    "  IF ROW_COUNT() = {rows} THEN COMMIT; ELSE ROLLBACK; END IF;\n"
    "END //\n"
    "DELIMITER ;\n"
    "CALL p();"
)
ORACLE_BLOCK = (
    "BEGIN\n"
    "  UPDATE t SET a = b WHERE a = 1;\n"
    "  IF SQL%ROWCOUNT = {rows} THEN COMMIT; ELSE ROLLBACK; END IF;\n"
    "END;\n"
    "/"
)
PG_DO_BLOCK = (
    "DO $$\n"
    "DECLARE n int;\n"
    "BEGIN\n"
    "  UPDATE t SET a = b WHERE a = 1;\n"
    "  GET DIAGNOSTICS n = ROW_COUNT;\n"
    "  IF n = 1 THEN COMMIT; ELSE ROLLBACK; END IF;\n"
    "END $$;"
)
ENGINE_FRAGMENTS = {
    "postgresql": {
        "BEGIN": "BEGIN;",
        "DO_BLOCK": PG_DO_BLOCK,
    },
    "cockroachdb": {
        "BEGIN": "BEGIN;",
        "DO_BLOCK": PG_DO_BLOCK,
    },
    "mysql": {
        "BEGIN": "START TRANSACTION;",
        "PROC_COMMIT": MYSQL_PROCEDURE.format(rows=1),
        "PROC_ROLLBACK": MYSQL_PROCEDURE.format(rows=100),
    },
    "mariadb": {
        "BEGIN": "START TRANSACTION;",
        "PROC_COMMIT": MYSQL_PROCEDURE.format(rows=1),
        "PROC_ROLLBACK": MYSQL_PROCEDURE.format(rows=100),
    },
    "oracle": {
        "PROC_COMMIT": ORACLE_BLOCK.format(rows=1),
        "PROC_ROLLBACK": ORACLE_BLOCK.format(rows=100),
    },
}
T_START = [(1, 2)]
T_DONE = [(2, 2)]

# One migration V1__case.sql per row: (id, fragments, success, t, h, history, engines).
# The expectations were fixed before any run.
EXPECT = [
    ("plain", ("UPD",), True, T_DONE, [], [True], ALL),
    ("plain_failure", ("UPD", "FAIL"), False, T_START, [], [False], ALL),
    ("commit_last", ("UPD", "COMMIT"), True, T_DONE, [], [True], ALL),
    ("commit_then_work", ("UPD", "COMMIT", "INS1"), True, T_DONE, [1], [True], ALL),
    ("commit_then_failure", ("UPD", "COMMIT", "FAIL"), False, T_DONE, [], [False], ALL),
    ("rollback_last", ("UPD", "ROLLBACK"), True, T_START, [], [True], ALL),
    ("rollback_then_work", ("UPD", "ROLLBACK", "INS1"), True, T_START, [1], [True], ALL),
    (
        "rollback_then_failure",
        ("INS1", "ROLLBACK", "FAIL"),
        False,
        T_START,
        [],
        [False],
        ALL,
    ),
    ("savepoint_rollback_to", ("SAVE", "UPD", "BACK", "INS1"), True, T_START, [1], [True], ALL),
    (
        "envelope",
        ("BEGIN", "UPD", "COMMIT"),
        True,
        T_DONE,
        [],
        [True],
        ["postgresql", "mysql", "mariadb"],
    ),
    (
        "envelope_failure",
        ("BEGIN", "UPD", "FAIL", "COMMIT"),
        False,
        T_START,
        [],
        [False],
        ["postgresql", "mysql", "mariadb"],
    ),
    (
        "envelope_rollback",
        ("BEGIN", "UPD", "ROLLBACK"),
        True,
        T_START,
        [],
        [True],
        ["postgresql", "mysql", "mariadb"],
    ),
    (
        "begin_mid",
        ("UPD", "BEGIN", "INS1"),
        True,
        T_DONE,
        [1],
        [True],
        ["postgresql", "mysql", "mariadb"],
    ),
    ("procedural_commit", ("PROC_COMMIT",), True, T_DONE, [], [True], ["oracle"]),
    ("procedural_rollback", ("PROC_ROLLBACK",), True, T_START, [], [True], ["oracle"]),
    ("procedural_refused", ("DO_BLOCK",), False, T_START, [], [False], ["postgresql"]),
]
# An engine the script's COMMIT is refused on says so in the error message.
ERROR_CONTAINS = {"procedural_refused": "invalid transaction termination"}

# Scenarios whose outcome was not known in advance; the pinned values are what
# was observed, with the server version it was observed on.
# Observed 2026-11-15 on MySQL 8.0.46 and MariaDB 11.8.8: the procedure's own
# COMMIT / ROLLBACK is honoured and nothing is left uncommitted.
CRDB = ["cockroachdb"]
RECORD = [
    # Observed on CockroachDB v24.3.18: a BEGIN inside dblift's transaction is refused
    # ("there is already a transaction in progress"); the run fails, nothing is left.
    ("envelope", ("BEGIN", "UPD", "COMMIT"), False, T_START, [], [False], CRDB),
    ("envelope_failure", ("BEGIN", "UPD", "FAIL", "COMMIT"), False, T_START, [], [False], CRDB),
    ("envelope_rollback", ("BEGIN", "UPD", "ROLLBACK"), False, T_START, [], [False], CRDB),
    ("begin_mid", ("UPD", "BEGIN", "INS1"), False, T_START, [], [False], CRDB),
    # CockroachDB v24.3.18 rejects the DO block itself (syntax error), so the run fails cleanly.
    ("do_block", ("DO_BLOCK",), False, T_START, [], [False], CRDB),
    ("procedural_commit", ("PROC_COMMIT",), True, T_DONE, [], [True], ["mysql", "mariadb"]),
    ("procedural_rollback", ("PROC_ROLLBACK",), True, T_START, [], [True], ["mysql", "mariadb"]),
]

# Flow scenarios: (id, {file: fragments}, undo fragments or None, caller_owned,
# success, t, h, history as (script, success)).
FLOWS = [
    (
        "callback_commit",
        {"beforeMigrate__cb.sql": ("INS7", "COMMIT"), "V1__case.sql": ("UPD",)},
        None,
        False,
        True,
        T_DONE,
        [7],
        [("V1__case.sql", True)],
    ),
    (
        "callback_rollback",
        {"beforeMigrate__cb.sql": ("INS7", "ROLLBACK"), "V1__case.sql": ("UPD",)},
        None,
        False,
        True,
        T_DONE,
        [],
        [("V1__case.sql", True)],
    ),
    (
        "undo_commit",
        {"V1__case.sql": ("UPD",)},
        ("UNDO_UPD", "COMMIT"),
        False,
        True,
        T_START,
        [],
        None,
    ),
    (
        "undo_rollback",
        {"V1__case.sql": ("UPD",)},
        ("UNDO_UPD", "ROLLBACK"),
        False,
        True,
        T_DONE,
        [],
        None,
    ),
    (
        "next_migration_is_atomic",
        {"V1__ended.sql": ("UPD", "COMMIT"), "V2__fails.sql": ("INS2", "FAIL")},
        None,
        False,
        False,
        T_DONE,
        [],
        [("V1__ended.sql", True), ("V2__fails.sql", False)],
    ),
    (
        "caller_owned_rollback",
        {"V1__case.sql": ("UPD", "ROLLBACK")},
        None,
        True,
        True,
        T_START,
        [],
        [("V1__case.sql", True)],
    ),
    (
        "caller_owned_commit_then_work",
        {"V1__case.sql": ("UPD", "COMMIT", "INS1")},
        None,
        True,
        True,
        T_DONE,
        [1],
        [("V1__case.sql", True)],
    ),
]


def _env(engine: str, name: str, default: str) -> str:
    return os.environ.get(f"DBLIFT_{engine.upper()}_{name}", default)


def _script(engine: str, fragments) -> str:
    table = {**FRAGMENTS, **ENGINE_FRAGMENTS[engine]}
    return "\n".join(table[name] for name in fragments) + "\n"


class Place:
    """A throwaway database (Oracle: user) and the means to read it back."""

    def __init__(self, engine: str):
        self.engine = engine
        host, port, user, password = DEFAULTS[engine]
        self.host = _env(engine, "HOST", host)
        self.port = int(_env(engine, "PORT", port))
        self.admin = _env(engine, "USERNAME", user)
        self.password = _env(engine, "PASSWORD", password)
        self.name = f"dblift_pin_{uuid.uuid4().hex[:8]}"
        self.schema = self.name

    def admin_connection(self, database=None):
        if self.engine in PG_FAMILY:
            import psycopg

            return psycopg.connect(
                host=self.host,
                port=self.port,
                user=self.admin,
                password=self.password,
                dbname=database or _env(self.engine, "DATABASE", DEFAULT_DATABASE[self.engine]),
                autocommit=True,
                connect_timeout=5,
            )
        if self.engine == "oracle":
            import oracledb

            conn = oracledb.connect(
                user=self.admin,
                password=self.password,
                dsn=f"{self.host}:{self.port}/{_env('oracle', 'SERVICE', 'FREEPDB1')}",
            )
            conn.autocommit = True
            return conn
        import pymysql

        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.admin,
            password=self.password,
            database=database,
            autocommit=True,
            connect_timeout=5,
        )

    def execute(self, sql: str, database=None) -> None:
        conn = self.admin_connection(database)
        try:
            conn.cursor().execute(sql)
        finally:
            conn.close()

    def query(self, sql: str) -> list:
        conn = self.admin_connection(self.name if self.engine != "oracle" else None)
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            return [tuple(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def provision(self) -> None:
        if self.engine in PG_FAMILY:
            self.schema = "public"
            self.execute(f'CREATE DATABASE "{self.name}"')
            database, prefix = self.name, ""
        elif self.engine == "oracle":
            self.name = self.name.upper()
            self.schema = self.name
            self.execute(f'CREATE USER {self.name} IDENTIFIED BY "{ORACLE_USER_PASSWORD}"')
            self.execute(
                f"GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW, "
                f"CREATE PROCEDURE, CREATE TRIGGER, UNLIMITED TABLESPACE TO {self.name}"
            )
            database, prefix = None, f"{self.name}."
        else:
            self.execute(f"CREATE DATABASE `{self.name}`")
            database, prefix = self.name, ""
        self.execute(f"CREATE TABLE {prefix}t (a int, b int)", database)
        self.execute(f"INSERT INTO {prefix}t VALUES (1, 2)", database)
        self.execute(f"CREATE TABLE {prefix}h (v int)", database)

    def drop(self) -> None:
        try:
            if self.engine == "postgresql":
                self.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')
            elif self.engine == "cockroachdb":
                self.execute(f'DROP DATABASE IF EXISTS "{self.name}" CASCADE')
            elif self.engine == "oracle":
                self.execute(f"DROP USER {self.name} CASCADE")
            else:
                self.execute(f"DROP DATABASE IF EXISTS `{self.name}`")
        except Exception:  # best effort: a place that never got created has nothing to drop
            pass

    def config(self, migrations_dir) -> DbliftConfig:
        common = dict(host=self.host, port=self.port, schema=self.schema)
        if self.engine in PG_FAMILY:
            database = PostgreSqlConfig(
                type=self.engine,
                database=self.name,
                username=self.admin,
                password=self.password,
                **common,
            )
        elif self.engine == "oracle":
            database = OracleConfig(
                type="oracle",
                service_name=_env("oracle", "SERVICE", "FREEPDB1"),
                username=self.name,
                password=ORACLE_USER_PASSWORD,
                **common,
            )
        else:
            database = MySqlConfig(
                type=self.engine,
                database=self.name,
                username=self.admin,
                password=self.password,
                **common,
            )
        config = DbliftConfig(database=database)
        config.migrations.directory = str(migrations_dir)
        return config

    def sqlalchemy_url(self) -> str:
        user, password = self.admin, self.password
        if self.engine == "oracle":
            user, password = self.name, ORACLE_USER_PASSWORD
        auth = f"{quote(user, safe='')}:{quote(password, safe='')}@{self.host}:{self.port}"
        if self.engine == "cockroachdb":
            url = make_url(build_sqlalchemy_url(self.config(".").database))
            # The insecure server ignores the password; the config dblift derives from a
            # caller's engine refuses an empty one.
            return url.set(password=url.password or "insecure").render_as_string(False)
        if self.engine == "postgresql":
            return f"postgresql+psycopg://{auth}/{self.name}"
        if self.engine == "oracle":
            return f"oracle+oracledb://{auth}/?service_name={_env('oracle', 'SERVICE', 'FREEPDB1')}"
        return f"{self.engine}+pymysql://{auth}/{self.name}"

    def run(self, migrations_dir, operation: str = "migrate", caller_owned: bool = False):
        """Run migrate or undo on dblift's own connection, or on one the caller opened."""
        if caller_owned:
            engine = create_engine(self.sqlalchemy_url())
            conn = engine.connect()
            try:
                client = DBLiftClient.from_sqlalchemy(
                    connection=conn,
                    schema=self.schema,
                    migrations_dir=migrations_dir,
                    logger=NullLog(),
                )
                return client.undo() if operation == "undo" else client.migrate()
            finally:
                try:
                    conn.close()
                finally:
                    engine.dispose()
        config = self.config(migrations_dir)
        provider = ProviderRegistry.create_provider(config)
        provider.create_connection()
        try:
            client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
            return client.undo() if operation == "undo" else client.migrate()
        finally:
            provider.close()

    def _prefix(self) -> str:
        return f"{self.name}." if self.engine == "oracle" else ""

    def t(self) -> list:
        return self.query(f"SELECT a, b FROM {self._prefix()}t ORDER BY a")

    def h(self) -> list:
        return sorted(row[0] for row in self.query(f"SELECT v FROM {self._prefix()}h"))

    def history(self) -> list:
        sql = (
            f"SELECT script, success FROM {self._prefix()}dblift_schema_history "
            "ORDER BY installed_rank"
        )
        return [(script, bool(success)) for script, success in self.query(sql)]


@pytest.fixture
def place(request):
    engine = request.param
    place = Place(engine)
    try:
        socket.create_connection((place.host, place.port), timeout=3).close()
    except OSError as exc:
        pytest.skip(
            f"{engine} not reachable at {place.host}:{place.port} ({exc}); set "
            f"DBLIFT_{engine.upper()}_HOST, _PORT, _USERNAME and _PASSWORD"
        )
    try:
        place.provision()
        yield place
    finally:
        place.drop()


def _combos(rows):
    """One pytest case per (engine, row): the engine is the indirect ``place`` parameter."""
    return [
        pytest.param(engine, *row[:-1], id=f"{engine}-{row[0]}")
        for row in rows
        for engine in row[-1]
    ]


def _assert_truthful(place, result, migrations: int) -> None:
    """The outcome dblift reports is the outcome the history and the data show."""
    history = place.history()
    assert history, "no history row at all"
    assert result.success == history[-1][1], (result.success, history)
    if result.success:
        assert len(history) >= migrations, history
    else:
        assert place.h() == [], "a failed run left a row nobody committed"
        assert place.t() in (T_START, T_DONE), place.t()


@pytest.mark.parametrize(
    "place, name, fragments, ok, t, h, history",
    _combos(EXPECT + RECORD),
    indirect=["place"],
)
def test_script_transaction_outcome(place, tmp_path, name, fragments, ok, t, h, history):
    create_migration(tmp_path, "V1__case.sql", _script(place.engine, fragments))

    result = place.run(tmp_path)

    if ok is not None:
        assert result.success is ok, result.error_message
    if name in ERROR_CONTAINS:
        assert ERROR_CONTAINS[name] in (result.error_message or "")
    if t is not None:
        assert place.t() == t
        assert place.h() == h
        assert [success for _, success in place.history()] == history
    _assert_truthful(place, result, 1)


@pytest.mark.parametrize(
    "place, name, files, undo, caller_owned, ok, t, h, history",
    _combos([(*flow, ENGINES) for flow in FLOWS]),
    indirect=["place"],
)
def test_script_transaction_flow(
    place, tmp_path, name, files, undo, caller_owned, ok, t, h, history
):
    for filename, fragments in files.items():
        create_migration(tmp_path, filename, _script(place.engine, fragments))
    if undo:
        create_undo_migration(tmp_path, "1", "case", _script(place.engine, undo))

    result = place.run(tmp_path, caller_owned=caller_owned)

    assert result.success is ok, result.error_message
    _assert_truthful(place, result, len([f for f in files if f.startswith("V")]))
    if undo:
        undone = place.run(tmp_path, "undo")
        assert undone.success, undone.error_message
    assert place.t() == t
    assert place.h() == h
    if history is not None:
        assert [row for row in place.history() if row[0] in dict(history)] == history
