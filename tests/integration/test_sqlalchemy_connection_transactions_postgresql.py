"""``from_sqlalchemy(connection=...)``: callbacks persist and a failed read leaves the connection usable."""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

pytestmark = pytest.mark.integration

CALLBACKS = ["beforeMigrate", "afterEachMigrate", "afterMigrate"]


def _url(config: dict, user: str = "", password: str = "") -> str:
    return (
        f"postgresql+psycopg://{quote(user or config['username'], safe='')}"
        f":{quote(password or config['password'], safe='')}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )


def run_callback_scenario(callback: str, url: str, tmp_path) -> None:
    """The callback's table exists once the caller has committed, whatever ran first."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / callback
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    (migrations / f"{callback}__cb.sql").write_text("CREATE TABLE cb (id integer);")

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with create_engine(url).connect() as conn:
            client = DBLiftClient.from_sqlalchemy(
                connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
            )
            result = client.migrate()
            client.close()
            conn.commit()
        assert result.success, getattr(result, "error", None)
        with admin.connect() as conn:
            tables = (
                conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = :s ORDER BY 1"),
                    {"s": schema},
                )
                .scalars()
                .all()
            )
        assert "cb" in tables and "t" in tables, tables
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_failed_read_scenario(url: str, tmp_path) -> None:
    """A role that cannot read the history gets the real cause on a clean connection."""
    uid = uuid.uuid4().hex[:8]
    schema, role, password = f"q_a_{uid}", f"q_a_reader_{uid}", f"Qa{uid}x1"
    migrations = tmp_path / "failed_read"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}'))
    try:
        DBLiftClient.from_sqlalchemy(
            engine=admin, schema=schema, migrations_dir=migrations, logger=NullLog()
        ).migrate()
        with admin.connect() as conn:
            conn.execute(text(f'CREATE TABLE "{schema}".mine (id integer)'))
            conn.execute(text(f'GRANT INSERT, SELECT ON "{schema}".mine TO {role}'))
        config = _config_of(url)
        with create_engine(_url(config, role, password)).connect() as conn:
            client = DBLiftClient.from_sqlalchemy(
                connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
            )
            for _ in range(2):
                message = client.info().error_message
                assert "permission denied" in message, message
                assert "aborted" not in message, message
                conn.rollback()
                assert not conn.in_transaction()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        admin.dispose()


def _tables(admin, schema: str) -> list:
    with admin.connect() as conn:
        return (
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :s ORDER BY 1"),
                {"s": schema},
            )
            .scalars()
            .all()
        )


def _client(conn, schema, migrations):
    return DBLiftClient.from_sqlalchemy(
        connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
    )


def run_pending_row_scenario(url: str, tmp_path) -> None:
    """A pending caller transaction prevents callbacks and migration work."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "pending_row"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    (migrations / "beforeMigrate__cb.sql").write_text("CREATE TABLE cb (id integer);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'CREATE TABLE "{schema}".mine (id integer)'))
    try:
        with create_engine(url).connect() as conn:
            conn.execute(text(f'INSERT INTO "{schema}".mine VALUES (1)'))
            client = _client(conn, schema, migrations)
            with pytest.raises(RuntimeError, match="caller.*transaction"):
                with client:
                    client.migrate()
            assert conn.in_transaction()
            assert conn.execute(text(f'SELECT count(*) FROM "{schema}".mine')).scalar() == 1
            conn.rollback()
        assert "cb" not in _tables(admin, schema)
        assert "t" not in _tables(admin, schema)
        with admin.connect() as conn:
            assert conn.execute(text(f'SELECT count(*) FROM "{schema}".mine')).scalar() == 0
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_migrate_refuses_pending_row_scenario(url: str, tmp_path) -> None:
    """Migrate refuses to run while the caller has an open transaction."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "migrate_pending_row"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        assert not conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
            {"schema": schema},
        ).scalar()
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'CREATE TABLE "{schema}".mine (id integer)'))
    try:
        with create_engine(url).connect() as conn:
            conn.execute(text(f'INSERT INTO "{schema}".mine VALUES (1)'))
            with pytest.raises(RuntimeError, match="caller.*transaction"):
                with _client(conn, schema, migrations) as client:
                    client.migrate()
            assert conn.in_transaction()
            assert conn.execute(text(f'SELECT count(*) FROM "{schema}".mine')).scalar() == 1
            conn.rollback()
        with admin.connect() as conn:
            assert conn.execute(text(f'SELECT count(*) FROM "{schema}".mine')).scalar() == 0
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_after_clean_scenario(url: str, tmp_path) -> None:
    """``afterClean`` runs in the caller's transaction and does not undo the clean."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "after_clean"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        DBLiftClient.from_sqlalchemy(
            engine=admin, schema=schema, migrations_dir=migrations, logger=NullLog()
        ).migrate()
        (migrations / "afterClean__cb.sql").write_text("CREATE TABLE cb (id integer);")
        with create_engine(url).connect() as conn:
            result = _client(conn, schema, migrations).clean(clean_enabled=True)
            conn.commit()
        assert result.success, getattr(result, "error", None)
        assert _tables(admin, schema) == ["cb"], _tables(admin, schema)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_validate_callback_scenario(url: str, tmp_path) -> None:
    """Validate refuses to run with caller work pending on the connection."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "validate_cb"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'CREATE TABLE "{schema}".mine (id integer)'))
    try:
        DBLiftClient.from_sqlalchemy(
            engine=admin, schema=schema, migrations_dir=migrations, logger=NullLog()
        ).migrate()
        (migrations / "beforeValidate__cb.sql").write_text("SELECT 1;")
        with create_engine(url).connect() as conn:
            conn.execute(text(f'INSERT INTO "{schema}".mine VALUES (1)'))
            client = _client(conn, schema, migrations)
            with pytest.raises(RuntimeError, match="caller.*transaction"):
                client.validate()
            pending = conn.execute(text(f'SELECT count(*) FROM "{schema}".mine')).scalar()
            conn.rollback()
        assert pending == 1
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_autocommit_scenario(url: str, tmp_path) -> None:
    """A caller-owned ``AUTOCOMMIT`` connection migrates, reports and validates."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "autocommit"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with admin.connect() as conn:
            client = _client(conn, schema, migrations)
            for name in ("migrate", "info", "validate"):
                result = getattr(client, name)()
                assert result.success, (name, getattr(result, "error_message", None))
                conn.commit()
        tables = _tables(admin, schema)
        assert "t" in tables and "dblift_schema_history" in tables, tables
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_read_then_migrate_scenario(url: str, tmp_path) -> None:
    """A read may autobegin; the caller must settle it before the next operation."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "read_then_migrate"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    try:
        with create_engine(url).connect() as conn:
            client = _client(conn, schema, migrations)
            assert client.info().success
            assert conn.in_transaction()
            with pytest.raises(RuntimeError, match="caller.*transaction"):
                client.migrate()
            conn.rollback()
            assert client.migrate().success
    finally:
        with create_engine(url, isolation_level="AUTOCOMMIT").connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def run_concurrent_index_scenario(url: str, tmp_path) -> None:
    """A ``CREATE INDEX CONCURRENTLY`` migration succeeds on a caller-owned connection."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "cic"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    (migrations / "V2__i.sql").write_text("CREATE INDEX CONCURRENTLY ix ON t (id);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with create_engine(url).connect() as conn:
            result = _client(conn, schema, migrations).migrate()
            conn.commit()
        assert result.success, getattr(result, "error", None)
        with admin.connect() as conn:
            indexes = (
                conn.execute(
                    text(
                        "SELECT schemaname FROM pg_indexes WHERE indexname = 'ix' AND schemaname = :s"
                    ),
                    {"s": schema},
                )
                .scalars()
                .all()
            )
        assert indexes == [schema]
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _config_of(url: str) -> dict:
    parsed = create_engine(url).url
    return {
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username,
        "password": parsed.password,
    }


@pytest.mark.parametrize("callback", CALLBACKS)
def test_callback_persists_on_a_caller_owned_connection(callback, postgresql_container, tmp_path):
    run_callback_scenario(callback, _url(postgresql_container), tmp_path)


def test_failed_history_read_leaves_the_caller_connection_usable(postgresql_container, tmp_path):
    run_failed_read_scenario(_url(postgresql_container), tmp_path)


def test_after_clean_callback_does_not_undo_clean(postgresql_container, tmp_path):
    run_after_clean_scenario(_url(postgresql_container), tmp_path)


def test_validate_refuses_the_callers_pending_work(postgresql_container, tmp_path):
    run_validate_callback_scenario(_url(postgresql_container), tmp_path)


def test_autocommit_caller_connection_migrates_and_reports(postgresql_container, tmp_path):
    run_autocommit_scenario(_url(postgresql_container), tmp_path)


def test_concurrent_index_migration_on_a_caller_owned_connection(postgresql_container, tmp_path):
    run_concurrent_index_scenario(_url(postgresql_container), tmp_path)


def test_before_migrate_callback_does_not_run_with_pending_caller_work(
    postgresql_container, tmp_path
):
    run_pending_row_scenario(_url(postgresql_container), tmp_path)


def test_migrate_does_not_silently_rollback_the_callers_pending_work(
    postgresql_container, tmp_path
):
    run_migrate_refuses_pending_row_scenario(_url(postgresql_container), tmp_path)


def test_read_then_migrate_requires_caller_to_settle_transaction(postgresql_container, tmp_path):
    run_read_then_migrate_scenario(_url(postgresql_container), tmp_path)
