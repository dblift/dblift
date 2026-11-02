"""An account that cannot read the history table gets an error, not an empty history.

``information_schema.TABLES``, ``sys.tables`` and ``ALL_TABLES`` list only tables the
account holds a privilege on, so a history table without SELECT used to read as absent:
``info`` exited 0 with every migration Pending. Oracle cannot tell a missing table from
one it may not read (ORA-00942 for both), so there ``info`` says the table does not exist.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

pytestmark = pytest.mark.integration

PASSWORD = "Rd#Pass123x"


@contextmanager
def _client(url: str, schema: str, migrations):
    """A client on its own engine, disposed so the account can be dropped afterwards."""
    engine = create_engine(url)
    client = DBLiftClient.from_sqlalchemy(
        engine, schema=schema, migrations_dir=migrations, logger=NullLog()
    )
    try:
        yield client
    finally:
        client.close()
        engine.dispose()


def _migrations(tmp_path, ddl: str):
    path = tmp_path / "migrations"
    path.mkdir()
    (path / "V1__t1.sql").write_text(ddl)
    (path / "V2__t2.sql").write_text(ddl.replace("t1", "t2"))
    return path


def _read(reader_url: str, schema: str, migrations, operation: str):
    """One client per call: a failed read can leave a caller-owned transaction open."""
    with _client(reader_url, schema, migrations) as client:
        return client.info() if operation == "info" else client.migrate(dry_run=True)


def _assert_refused(reader_url: str, schema: str, migrations, needle: str) -> None:
    for operation in ("info", "migrate"):
        result = _read(reader_url, schema, migrations, operation)
        assert not result.success, operation
        assert needle in str(result.error_message), result.error_message
        assert not getattr(result, "migrations", None)


def _assert_reads_history(reader_url: str, schema: str, migrations) -> None:
    info = _read(reader_url, schema, migrations, "info")
    assert info.success, info.error_message
    assert {m.status for m in info.migrations} == {"SUCCESS"}
    assert info.current_schema_version == "2"


def run_scenario_mysql(url: str, reader_url_for, tmp_path) -> None:
    """``url`` is an admin URL (MySQL or MariaDB); ``reader_url_for(user, password, database)``."""
    uid = uuid.uuid4().hex[:8]
    schema, user = f"q_c_hist_{uid}", f"q_c_r{uid}"
    migrations = _migrations(tmp_path, "CREATE TABLE t1 (id INT);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE `{schema}`"))
        conn.execute(text(f"CREATE USER '{user}'@'%' IDENTIFIED BY '{PASSWORD}'"))
    try:
        with _client(url, schema, migrations) as applied:
            result = applied.migrate()
            assert result.success, result.error_message
        with admin.connect() as conn:
            # The account can use the database but holds nothing on the history table.
            conn.execute(text(f"CREATE TABLE `{schema}`.other (id INT)"))
            conn.execute(text(f"GRANT SELECT ON `{schema}`.other TO '{user}'@'%'"))
        reader_url = reader_url_for(user, PASSWORD, schema)

        _assert_refused(reader_url, schema, migrations, "denied")

        with admin.connect() as conn:
            conn.execute(text(f"GRANT SELECT ON `{schema}`.* TO '{user}'@'%'"))
        _assert_reads_history(reader_url, schema, migrations)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS `{schema}`"))
            conn.execute(text(f"DROP USER IF EXISTS '{user}'@'%'"))
        admin.dispose()


def run_scenario_sqlserver(url: str, reader_url_for, tmp_path) -> None:
    """``url`` is an admin URL on ``master``; ``reader_url_for(login, password, database)``."""
    uid = uuid.uuid4().hex[:8]
    database, schema, reader, owner = f"q_c_hist_{uid}", "q_c_s", f"q_c_r{uid}", f"q_c_o{uid}"
    migrations = _migrations(tmp_path, f"CREATE TABLE {schema}.t1 (id INT);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE [{database}]"))
        for login in (reader, owner):
            conn.execute(
                text(f"CREATE LOGIN [{login}] WITH PASSWORD='{PASSWORD}', CHECK_POLICY=OFF")
            )
            conn.execute(text(f"USE [{database}]; CREATE USER [{login}] FOR LOGIN [{login}]"))
        conn.execute(text(f"USE [{database}]; ALTER ROLE db_owner ADD MEMBER [{owner}]"))
    try:
        with _client(reader_url_for(owner, PASSWORD, database), schema, migrations) as applied:
            result = applied.migrate()
            assert result.success, result.error_message
        with admin.connect() as conn:
            # The login can use the schema but holds nothing on the history table.
            conn.execute(text(f"USE [{database}]; CREATE TABLE [{schema}].other (id INT)"))
            conn.execute(text(f"USE [{database}]; GRANT SELECT ON [{schema}].other TO [{reader}]"))
        reader_url = reader_url_for(reader, PASSWORD, database)

        _assert_refused(reader_url, schema, migrations, "permission was denied")

        with admin.connect() as conn:
            conn.execute(
                text(f"USE [{database}]; GRANT SELECT ON SCHEMA::[{schema}] TO [{reader}]")
            )
        _assert_reads_history(reader_url, schema, migrations)
    finally:
        with admin.connect() as conn:
            conn.execute(text("USE master"))  # a pooled connection keeps its last USE
            conn.execute(
                text(f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            )
            conn.execute(text(f"DROP DATABASE [{database}]"))
            for login in (reader, owner):
                conn.execute(text(f"DROP LOGIN [{login}]"))
        admin.dispose()


def run_scenario_oracle(url: str, reader_url_for, tmp_path) -> None:
    """``url`` is an admin URL; ``reader_url_for(user, password)``.

    ORA-00942 covers a missing table and one the account may not read, so ``info`` can
    only report that the table is not there; the other engines refuse the read.
    """
    uid = uuid.uuid4().hex[:8].upper()
    owner, reader = f"Q_C_O{uid}", f"Q_C_R{uid}"
    migrations = _migrations(tmp_path, "CREATE TABLE t1 (id NUMBER)")
    admin = create_engine(url)
    with admin.connect() as conn:
        conn.execute(
            text(f'CREATE USER {owner} IDENTIFIED BY "{PASSWORD}" QUOTA UNLIMITED ON users')
        )
        conn.execute(text(f"GRANT CONNECT, RESOURCE, UNLIMITED TABLESPACE TO {owner}"))
        conn.execute(text(f'CREATE USER {reader} IDENTIFIED BY "{PASSWORD}"'))
        conn.execute(text(f"GRANT CREATE SESSION TO {reader}"))
    try:
        with _client(reader_url_for(owner, PASSWORD), owner, migrations) as applied:
            result = applied.migrate()
            assert result.success, result.error_message
        reader_url = reader_url_for(reader, PASSWORD)

        for operation in ("info", "migrate"):
            result = _read(reader_url, owner, migrations, operation)
            assert result.success, result.error_message
            assert result.history_table_exists is False
            assert {m.status for m in result.migrations} == {"PENDING"}

        with admin.connect() as conn:
            conn.execute(text(f"GRANT SELECT ON {owner}.dblift_schema_history TO {reader}"))
        _assert_reads_history(reader_url, owner, migrations)
    finally:
        with admin.connect() as conn:
            for user in (owner, reader):
                conn.execute(text(f"DROP USER {user} CASCADE"))
        admin.dispose()


def _url(driver: str, config: dict, user: str, password: str, path: str = "") -> str:
    return (
        f"{driver}://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{config['host']}:{config['port']}/{path}"
    )


def test_mysql_account_without_select_on_history_table_gets_an_error(mysql_container, tmp_path):
    config = mysql_container

    def reader_url_for(user, password, database):
        return _url("mysql+pymysql", config, user, password, database)

    run_scenario_mysql(
        reader_url_for(config["username"], config["password"], config["database"]),
        reader_url_for,
        tmp_path,
    )


def test_sqlserver_login_without_select_on_history_table_gets_an_error(
    sqlserver_container, tmp_path
):
    config = sqlserver_container

    def reader_url_for(login, password, database):
        return _url("mssql+pymssql", config, login, password, database)

    run_scenario_sqlserver(
        reader_url_for(config["username"], config["password"], "master"), reader_url_for, tmp_path
    )


def test_oracle_account_without_select_on_history_table_reports_it_missing(
    oracle_container, tmp_path
):
    config = oracle_container

    def reader_url_for(user, password):
        return (
            _url("oracle+oracledb", config, user, password) + f"?service_name={config['service']}"
        )

    run_scenario_oracle(
        reader_url_for(config["username"], config["password"]), reader_url_for, tmp_path
    )
