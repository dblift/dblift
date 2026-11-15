"""Work after a script's own COMMIT is committed with the history row.

Engines that report nothing about the transaction a script ended keep the
default: dblift commits whatever follows the script's COMMIT together with the
history row, and a failure after that COMMIT keeps the committed part. These
tests are pins: they pass before and after the change they guard, and fail if
that default is broken.

They run against live PostgreSQL, MySQL, MariaDB and Oracle servers. Each test
provisions a throwaway database (Oracle: user) with an administrative account
and drops it afterwards. An engine that cannot be reached is skipped; set
DBLIFT_<ENGINE>_HOST / _PORT / _USERNAME / _PASSWORD (PostgreSQL also
_DATABASE, Oracle also _SERVICE) to point at one.
"""

import os
import uuid

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.mysql.config import MySqlConfig
from dblift.db.plugins.oracle.config import OracleConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_migration

pytestmark = pytest.mark.integration

ENGINES = ["postgresql", "mysql", "mariadb", "oracle"]
DEFAULTS = {
    "postgresql": ("localhost", "5432", "postgres", "postgres"),
    "mysql": ("localhost", "3306", "root", "root"),
    "mariadb": ("localhost", "3306", "root", "root"),
    "oracle": ("localhost", "1521", "system", "oracle"),
}
ORACLE_USER_PASSWORD = "Dblift_Pin1x"

COMMITTED_THEN_MORE = "INSERT INTO t VALUES (1);\nCOMMIT;\nINSERT INTO t VALUES (2);\n"
COMMITTED_THEN_FAILS = "INSERT INTO t VALUES (1);\nCOMMIT;\nINSERT INTO nosuch VALUES (2);\n"


def _env(engine: str, name: str, default: str) -> str:
    return os.environ.get(f"DBLIFT_{engine.upper()}_{name}", default)


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
        if self.engine == "postgresql":
            import psycopg

            return psycopg.connect(
                host=self.host,
                port=self.port,
                user=self.admin,
                password=self.password,
                dbname=database or _env("postgresql", "DATABASE", "postgres"),
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
            return list(cursor.fetchall())
        finally:
            conn.close()

    def provision(self) -> None:
        if self.engine == "postgresql":
            self.schema = "public"
            self.execute(f'CREATE DATABASE "{self.name}"')
            self.execute("CREATE TABLE t (a int)", self.name)
        elif self.engine == "oracle":
            self.name = self.name.upper()
            self.schema = self.name
            self.execute(f'CREATE USER {self.name} IDENTIFIED BY "{ORACLE_USER_PASSWORD}"')
            self.execute(
                f"GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW, "
                f"CREATE PROCEDURE, CREATE TRIGGER, UNLIMITED TABLESPACE TO {self.name}"
            )
            self.execute(f"CREATE TABLE {self.name}.t (a int)")
        else:
            self.execute(f"CREATE DATABASE `{self.name}`")
            self.execute("CREATE TABLE t (a int)", self.name)

    def drop(self) -> None:
        try:
            if self.engine == "postgresql":
                self.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')
            elif self.engine == "oracle":
                self.execute(f"DROP USER {self.name} CASCADE")
            else:
                self.execute(f"DROP DATABASE IF EXISTS `{self.name}`")
        except Exception:  # best effort: a place that never got created has nothing to drop
            pass

    def config(self, migrations_dir) -> DbliftConfig:
        common = dict(host=self.host, port=self.port, schema=self.schema)
        if self.engine == "postgresql":
            database = PostgreSqlConfig(
                type="postgresql",
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

    def migrate(self, migrations_dir):
        config = self.config(migrations_dir)
        provider = ProviderRegistry.create_provider(config)
        provider.create_connection()
        try:
            client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
            return client.migrate()
        finally:
            provider.close()

    def rows(self) -> list:
        prefix = f"{self.name}." if self.engine == "oracle" else ""
        return [row[0] for row in self.query(f"SELECT a FROM {prefix}t ORDER BY a")]

    def history(self) -> list:
        prefix = f"{self.name}." if self.engine == "oracle" else ""
        sql = f"SELECT success FROM {prefix}dblift_schema_history ORDER BY installed_rank"
        return [bool(row[0]) for row in self.query(sql)]


@pytest.fixture(params=ENGINES)
def place(request):
    engine = request.param
    place = Place(engine)
    try:
        place.admin_connection().close()
    except Exception as exc:
        pytest.skip(
            f"{engine} not reachable ({type(exc).__name__}); set DBLIFT_{engine.upper()}_HOST, "
            "_PORT, _USERNAME and _PASSWORD"
        )
    try:
        place.provision()
        yield place
    finally:
        place.drop()


def test_work_after_the_scripts_commit_is_committed_with_the_history_row(place, tmp_path):
    create_migration(tmp_path, "V1__case.sql", COMMITTED_THEN_MORE)

    result = place.migrate(tmp_path)

    assert result.success, result.error_message
    assert place.rows() == [1, 2]
    assert place.history() == [True]


def test_commit_then_failure_keeps_the_committed_part_and_records_a_failed_row(place, tmp_path):
    create_migration(tmp_path, "V1__case.sql", COMMITTED_THEN_FAILS)

    result = place.migrate(tmp_path)

    assert not result.success
    assert place.rows() == [1]
    assert place.history() == [False]
