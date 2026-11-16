"""Migration scripts that end or leave open their own transaction on SQL Server.

A script may commit or roll back the transaction the run opened for it, or
leave one open. These tests run real scripts against a REAL SQL Server
container and check three things after each run: the reported outcome, the
data, and the history rows. dblift connects as a throwaway non-sysadmin login
that owns schema ``app``; ``sa`` provisions the database and reads state back.

Prerequisites: a SQL Server instance reachable at DBLIFT_SQLSERVER_HOST /
DBLIFT_SQLSERVER_PORT (default localhost:1433), with the ``sa`` password in
DBLIFT_SQLSERVER_SA_PASSWORD.
"""

import os
import uuid
from urllib.parse import quote

import pymssql
import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.db.plugins.sqlserver.config import SqlServerConfig
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_migration, create_undo_migration

pytestmark = [pytest.mark.integration, pytest.mark.sqlserver]

HOST = os.environ.get("DBLIFT_SQLSERVER_HOST", "localhost")
PORT = int(os.environ.get("DBLIFT_SQLSERVER_PORT", "1433"))
SA_PASSWORD = os.environ.get("DBLIFT_SQLSERVER_SA_PASSWORD", "YourStrong@Passw0rd")
LOGIN_PASSWORD = "Dblift_Tx1!"
SCHEMA = "app"
UPD = "UPDATE app.t SET a = b WHERE a = 1;"

ENDED = f"BEGIN TRAN;\n{UPD}\nIF @@ROWCOUNT = 100 COMMIT; ELSE ROLLBACK;\nGO\n"


def _connect(database: str) -> "pymssql.Connection":
    """A raw, autocommit ``sa`` connection."""
    return pymssql.connect(
        server=HOST,
        port=PORT,
        user="sa",
        password=SA_PASSWORD,
        database=database,
        autocommit=True,
    )


@pytest.fixture
def account():
    """A throwaway database and a non-sysadmin login owning schema ``app``."""
    suffix = uuid.uuid4().hex[:8]
    db_name = f"dblift_tx_db_{suffix}"
    login = f"dblift_tx_{suffix}"
    conn = _connect("master")
    try:
        try:
            conn.cursor().execute(f"CREATE DATABASE [{db_name}]")
            conn.cursor().execute(
                f"CREATE LOGIN [{login}] WITH PASSWORD = N'{LOGIN_PASSWORD}', "
                "CHECK_POLICY = OFF, CHECK_EXPIRATION = OFF"
            )
            db_conn = _connect(db_name)
            try:
                cursor = db_conn.cursor()
                cursor.execute(f"CREATE USER [{login}] FOR LOGIN [{login}]")
                cursor.execute(f"EXEC(N'CREATE SCHEMA [{SCHEMA}] AUTHORIZATION [{login}]')")
                cursor.execute(f"ALTER USER [{login}] WITH DEFAULT_SCHEMA = [{SCHEMA}]")
                cursor.execute(f"ALTER ROLE db_owner ADD MEMBER [{login}]")
                cursor.execute("CREATE TABLE app.t (a int, b int)")
                cursor.execute("INSERT INTO app.t VALUES (1, 2)")
                cursor.execute("CREATE TABLE app.h (v int)")
            finally:
                db_conn.close()
            yield db_name, login
        finally:
            conn.cursor().execute(
                f"IF EXISTS (SELECT 1 FROM sys.databases WHERE name = '{db_name}') "
                "BEGIN "
                f"ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE [{db_name}]; "
                "END"
            )
            conn.cursor().execute(
                f"IF EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{login}') "
                f"DROP LOGIN [{login}]"
            )
    finally:
        conn.close()


def _config(account, migrations_dir) -> DbliftConfig:
    db_name, login = account
    database = SqlServerConfig(
        type="sqlserver",
        host=HOST,
        port=PORT,
        database=db_name,
        username=login,
        password=LOGIN_PASSWORD,
        schema=SCHEMA,
        encrypt=False,
    )
    config = DbliftConfig(database=database)
    config.migrations.directory = str(migrations_dir)
    return config


def _run(account, migrations_dir, operation: str):
    config = _config(account, migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
        return client.undo() if operation == "undo" else client.migrate()
    finally:
        provider.close()


def _migrate(account, migrations_dir):
    return _run(account, migrations_dir, "migrate")


def _undo(account, migrations_dir):
    return _run(account, migrations_dir, "undo")


def _rows(account, sql: str) -> list:
    conn = _connect(account[0])
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return [tuple(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _t(account) -> list:
    return _rows(account, "SELECT a, b FROM app.t")


def _h(account) -> list:
    return sorted(row[0] for row in _rows(account, "SELECT v FROM app.h"))


def _history(account) -> list:
    return [
        (script, bool(success))
        for script, success in _rows(
            account,
            "SELECT script, success FROM app.dblift_schema_history ORDER BY installed_rank",
        )
    ]


def _assert_truthful(account, result, migrations: int = 1) -> None:
    """The outcome dblift reports is the outcome the history and the data show."""
    history = _history(account)
    assert history, "no history row at all"
    assert result.success == history[-1][1], (result.success, history)
    if result.success:
        assert len(history) >= migrations, history
    else:
        assert _h(account) == [], "a failed run left a row nobody committed"
        assert _t(account) in ([(1, 2)], [(2, 2)]), _t(account)


CASES = [
    (
        "balanced_across_units",
        f"BEGIN TRAN;\nGO\n{UPD}\nGO\nCOMMIT;\nGO\n",
        True,
        [(2, 2)],
        [],
        [True],
    ),
    ("save_transaction", f"SAVE TRANSACTION s1;\n{UPD}\nGO\n", True, [(2, 2)], [], [True]),
    (
        "own_tran_commit_branch",
        f"BEGIN TRAN;\n{UPD}\nIF @@ROWCOUNT = 1 COMMIT; ELSE ROLLBACK;\nGO\n",
        True,
        [(2, 2)],
        [],
        [True],
    ),
    ("own_tran_rollback_branch", ENDED, True, [(1, 2)], [], [True]),
    (
        "commit_without_begin",
        f"{UPD}\nIF @@ROWCOUNT = 1 COMMIT; ELSE ROLLBACK;\nGO\n",
        True,
        [(2, 2)],
        [],
        [True],
    ),
    (
        "rollback_without_begin",
        f"{UPD}\nIF @@ROWCOUNT = 100 COMMIT; ELSE ROLLBACK;\nGO\n",
        True,
        [(1, 2)],
        [],
        [True],
    ),
    ("left_open", f"BEGIN TRAN;\n{UPD}\nGO\n", False, [(1, 2)], [], [False]),
    (
        "rollback_then_reopened",
        f"{UPD}\nROLLBACK;\nBEGIN TRAN;\nINSERT INTO app.h VALUES (1);\nGO\n",
        False,
        [(1, 2)],
        [],
        [False],
    ),
    (
        "committed_then_reopened",
        f"{UPD}\nCOMMIT;\nBEGIN TRAN;\nINSERT INTO app.h VALUES (1);\nGO\n",
        False,
        [(2, 2)],
        [],
        [False],
    ),
    (
        "ended_then_failing",
        f"{UPD}\nCOMMIT;\nGO\nINSERT INTO app.nosuch VALUES (1);\nGO\n",
        False,
        [(2, 2)],
        [],
        [False],
    ),
    (
        "plain_failure_is_atomic",
        f"{UPD}\nGO\nINSERT INTO app.nosuch VALUES (1);\nGO\n",
        False,
        [(1, 2)],
        [],
        [False],
    ),
    (
        "uncommittable_is_rolled_back_by_the_server",
        f"SET XACT_ABORT ON;\nGO\n{UPD}\nBEGIN TRY UPDATE app.t SET a = 1/0 END TRY BEGIN CATCH END CATCH;\nGO\n",
        False,
        [(1, 2)],
        [],
        [False],
    ),
    (
        "commit_then_work",
        f"{UPD}\nCOMMIT;\nGO\nINSERT INTO app.h VALUES (1);\nGO\n",
        True,
        [(2, 2)],
        [1],
        [True],
    ),
    (
        "rollback_then_work",
        f"{UPD}\nROLLBACK;\nGO\nINSERT INTO app.h VALUES (1);\nGO\n",
        True,
        [(1, 2)],
        [1],
        [True],
    ),
    (
        "savepoint_rollback_to",
        f"SAVE TRANSACTION s1;\n{UPD}\nROLLBACK TRANSACTION s1;\n"
        "INSERT INTO app.h VALUES (1);\nGO\n",
        True,
        [(1, 2)],
        [1],
        [True],
    ),
    (
        "envelope_failure",
        f"BEGIN TRAN;\nGO\n{UPD}\nGO\nINSERT INTO app.nosuch VALUES (1);\nGO\nCOMMIT;\nGO\n",
        False,
        [(1, 2)],
        [],
        [False],
    ),
    ("plain", f"{UPD}\nGO\n", True, [(2, 2)], [], [True]),
    (
        "rollback_then_failure",
        "INSERT INTO app.h VALUES (1);\nROLLBACK;\nGO\nINSERT INTO app.nosuch VALUES (1);\nGO\n",
        False,
        [(1, 2)],
        [],
        [False],
    ),
]


@pytest.mark.parametrize("name, script, ok, t, h, history", CASES, ids=[c[0] for c in CASES])
def test_script_transaction_outcome(account, tmp_path, name, script, ok, t, h, history):
    create_migration(tmp_path, "V1__case.sql", script)

    result = _migrate(account, tmp_path)

    assert result.success is ok, result.error_message
    assert _t(account) == t
    assert _h(account) == h
    assert [success for _, success in _history(account)] == history
    _assert_truthful(account, result)


def _migrate_caller_owned(account, tmp_path):
    db_name, login = account
    url = (
        f"mssql+pymssql://{quote(login, safe='')}:{quote(LOGIN_PASSWORD, safe='')}"
        f"@{HOST}:{PORT}/{db_name}"
    )
    engine = create_engine(url)
    conn = engine.connect()
    try:
        client = DBLiftClient.from_sqlalchemy(
            connection=conn, schema=SCHEMA, migrations_dir=tmp_path, logger=NullLog()
        )
        return client.migrate()
    finally:
        try:
            conn.close()
        finally:
            engine.dispose()


def test_caller_owned_connection_script_that_ends_its_transaction(account, tmp_path):
    create_migration(tmp_path, "V1__case.sql", ENDED)

    result = _migrate_caller_owned(account, tmp_path)

    assert result.success, result.error_message
    assert _t(account) == [(1, 2)]
    assert [success for _, success in _history(account)] == [True]
    _assert_truthful(account, result)


def test_caller_owned_connection_commit_then_work(account, tmp_path):
    create_migration(
        tmp_path, "V1__case.sql", f"{UPD}\nCOMMIT;\nGO\nINSERT INTO app.h VALUES (1);\nGO\n"
    )

    result = _migrate_caller_owned(account, tmp_path)

    assert result.success, result.error_message
    assert _t(account) == [(2, 2)]
    assert _h(account) == [1]
    assert [success for _, success in _history(account)] == [True]
    _assert_truthful(account, result)


def test_ordinary_migration_after_an_ended_one_is_atomic(account, tmp_path):
    create_migration(tmp_path, "V1__ended.sql", ENDED)
    create_migration(
        tmp_path,
        "V2__fails.sql",
        "INSERT INTO app.h VALUES (2);\nGO\nINSERT INTO app.nosuch VALUES (1);\nGO\n",
    )

    result = _migrate(account, tmp_path)

    assert not result.success
    assert _history(account) == [("V1__ended.sql", True), ("V2__fails.sql", False)]
    assert _h(account) == []
    _assert_truthful(account, result, 2)


def test_callback_that_ends_its_transaction_does_not_break_the_run(account, tmp_path):
    create_migration(
        tmp_path,
        "beforeMigrate__cb.sql",
        "BEGIN TRAN;\nINSERT INTO app.h VALUES (7);\nROLLBACK;\nGO\n",
    )
    create_migration(tmp_path, "V1__case.sql", f"{UPD}\nGO\n")

    result = _migrate(account, tmp_path)

    assert result.success, result.error_message
    assert _t(account) == [(2, 2)] and _h(account) == []
    _assert_truthful(account, result)


def test_callback_that_commits_keeps_its_work(account, tmp_path):
    create_migration(
        tmp_path,
        "beforeMigrate__cb.sql",
        "INSERT INTO app.h VALUES (7);\nCOMMIT;\nGO\n",
    )
    create_migration(tmp_path, "V1__case.sql", f"{UPD}\nGO\n")

    result = _migrate(account, tmp_path)

    assert result.success, result.error_message
    assert _t(account) == [(2, 2)] and _h(account) == [7]
    _assert_truthful(account, result)


def test_undo_script_that_ends_its_transaction_succeeds(account, tmp_path):
    create_migration(tmp_path, "V1__case.sql", f"{UPD}\nGO\n")
    create_undo_migration(
        tmp_path,
        "1",
        "case",
        "BEGIN TRAN;\nUPDATE app.t SET a = 1 WHERE a = 2;\n"
        "IF @@ROWCOUNT = 100 COMMIT; ELSE ROLLBACK;\nGO\n",
    )
    applied = _migrate(account, tmp_path)
    assert applied.success, applied.error_message
    _assert_truthful(account, applied)

    undo_result = _undo(account, tmp_path)

    assert undo_result.success, undo_result.error_message
    assert _t(account) == [(2, 2)]


def test_undo_script_that_commits_succeeds(account, tmp_path):
    create_migration(tmp_path, "V1__case.sql", f"{UPD}\nGO\n")
    create_undo_migration(
        tmp_path, "1", "case", "UPDATE app.t SET a = 1 WHERE a = 2;\nCOMMIT;\nGO\n"
    )
    applied = _migrate(account, tmp_path)
    assert applied.success, applied.error_message
    _assert_truthful(account, applied)

    undo_result = _undo(account, tmp_path)

    assert undo_result.success, undo_result.error_message
    assert _t(account) == [(1, 2)]


# Scripts that opt out of the wrapping transaction with a leading comment: the
# script's own BEGIN / COMMIT / ROLLBACK are the real ones.
D = "-- dblift:no-transaction\n"
NT_CASES = [
    (
        "nt_conditional_commit",
        f"BEGIN TRAN;\n{UPD}\nIF @@ROWCOUNT = 1 COMMIT; ELSE ROLLBACK;\nGO\n",
        True,
        [(2, 2)],
        [],
        [True],
        None,
    ),
    (
        "nt_conditional_rollback",
        f"BEGIN TRAN;\n{UPD}\nIF @@ROWCOUNT = 100 COMMIT; ELSE ROLLBACK;\nGO\n",
        True,
        [(1, 2)],
        [],
        [True],
        None,
    ),
    (
        "nt_begin_and_commit_in_separate_units",
        f"BEGIN TRAN;\nGO\n{UPD}\nGO\nCOMMIT;\nGO\n",
        True,
        [(2, 2)],
        [],
        [True],
        None,
    ),
    ("nt_left_open", f"BEGIN TRAN;\nGO\n{UPD}\nGO\n", False, [(1, 2)], [], [False], None),
    (
        "nt_commit_a_open_b",
        f"BEGIN TRAN;\nGO\n{UPD}\nGO\nCOMMIT;\nGO\n"
        "BEGIN TRAN;\nGO\nINSERT INTO app.h VALUES (1);\nGO\n",
        False,
        [(2, 2)],
        [],
        [False],
        None,
    ),
    (
        "nt_commit_without_begin",
        f"{UPD}\nIF @@ROWCOUNT = 1 COMMIT; ELSE ROLLBACK;\nGO\n",
        False,
        [(2, 2)],
        [],
        [False],
        "no corresponding BEGIN TRANSACTION",
    ),
    (
        "nt_commit_then_failure",
        f"{UPD}\nGO\nINSERT INTO app.nosuch VALUES (1);\nGO\n",
        False,
        [(2, 2)],
        [],
        [False],
        None,
    ),
]


@pytest.mark.parametrize(
    "name, script, ok, t, h, history, error", NT_CASES, ids=[c[0] for c in NT_CASES]
)
def test_no_transaction_outcome(account, tmp_path, name, script, ok, t, h, history, error):
    create_migration(tmp_path, "V1__case.sql", D + script)

    result = _migrate(account, tmp_path)

    assert result.success is ok, result.error_message
    if error:
        assert error in (result.error_message or ""), result.error_message
    assert _t(account) == t
    assert _h(account) == h
    assert [success for _, success in _history(account)] == history
    _assert_truthful(account, result)


def _success_rows(account) -> list:
    """History rows with success true; a history table that was never created has none."""
    try:
        return [row for row in _history(account) if row[1]]
    except Exception:
        return []


def test_no_transaction_then_ordinary_failure(account, tmp_path):
    create_migration(tmp_path, "V1__nt.sql", f"{D}{UPD}\nGO\n")
    create_migration(
        tmp_path,
        "V2__fails.sql",
        "INSERT INTO app.h VALUES (2);\nGO\nINSERT INTO app.nosuch VALUES (1);\nGO\n",
    )

    result = _migrate(account, tmp_path)

    assert not result.success
    assert _history(account) == [("V1__nt.sql", True), ("V2__fails.sql", False)]
    assert _h(account) == []
    assert _t(account) == [(2, 2)]
    _assert_truthful(account, result, 2)


def test_no_transaction_callback_that_commits_keeps_its_work(account, tmp_path):
    create_migration(
        tmp_path,
        "beforeMigrate__cb.sql",
        f"{D}BEGIN TRAN;\nINSERT INTO app.h VALUES (7);\nCOMMIT;\nGO\n",
    )
    create_migration(tmp_path, "V1__case.sql", f"{UPD}\nGO\n")

    result = _migrate(account, tmp_path)

    assert result.success, result.error_message
    assert _h(account) == [7]
    assert _t(account) == [(2, 2)]
    assert [success for _, success in _history(account)] == [True]
    _assert_truthful(account, result)


def test_no_transaction_callback_left_open_fails_the_run(account, tmp_path):
    create_migration(
        tmp_path,
        "beforeMigrate__cb.sql",
        f"{D}BEGIN TRAN;\nINSERT INTO app.h VALUES (7);\nGO\n",
    )
    create_migration(tmp_path, "V1__case.sql", f"{UPD}\nGO\n")

    result = _migrate(account, tmp_path)

    assert not result.success
    assert _h(account) == []
    assert _t(account) == [(1, 2)]
    assert _success_rows(account) == []


def test_no_transaction_undo_script_that_commits_succeeds(account, tmp_path):
    create_migration(tmp_path, "V1__case.sql", f"{UPD}\nGO\n")
    create_undo_migration(
        tmp_path,
        "1",
        "case",
        f"{D}BEGIN TRAN;\nUPDATE app.t SET a = 1 WHERE a = 2;\nCOMMIT;\nGO\n",
    )
    applied = _migrate(account, tmp_path)
    assert applied.success, applied.error_message
    _assert_truthful(account, applied)

    undo_result = _undo(account, tmp_path)

    assert undo_result.success, undo_result.error_message
    assert _t(account) == [(1, 2)]


def test_no_transaction_refused_on_a_caller_owned_connection(account, tmp_path):
    create_migration(tmp_path, "V1__case.sql", f"{D}{UPD}\nGO\n")

    result = _migrate_caller_owned(account, tmp_path)

    assert not result.success
    assert "from_sqlalchemy" in (result.error_message or ""), result.error_message
    assert _t(account) == [(1, 2)]
    assert _success_rows(account) == []
