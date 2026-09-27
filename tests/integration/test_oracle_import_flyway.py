"""Live Oracle regression: ``import-flyway`` reads the table Flyway creates.

Flyway's Oracle support creates its history table as a quoted lowercase
name with quoted lowercase columns (``"flyway_schema_history"``,
``"installed_rank"``, ...) plus an unquoted synonym, see
``OracleDatabase.getRawCreateScript`` in flyway/flyway. The import must read
that shape, a hand-built uppercase table, and a configured table name.

Prerequisites: an Oracle instance reachable at localhost:1521, service
FREEPDB1, connectable as ``system`` / ``oracle``.
"""

import datetime
import uuid

import pytest

from dblift.api import DBLiftClient
from dblift.config.dblift_config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.sql_validator._flyway_compatibility import validate_flyway_compatibility
from dblift.db.plugins.oracle.config import OracleConfig
from dblift.db.provider_registry import ProviderRegistry

pytestmark = [pytest.mark.integration, pytest.mark.oracle]

SUCCESS_ON = datetime.datetime(2024, 1, 2, 3, 4, 5)
FAILED_ON = datetime.datetime(2024, 1, 3, 4, 5, 6)


def _config(schema=None):
    return DbliftConfig(
        database=OracleConfig(
            type="oracle",
            host="localhost",
            port=1521,
            service_name="FREEPDB1",
            username="system",
            password="oracle",
            schema=schema,
        )
    )


def _flyway_ddl(schema, table):
    """Flyway's own Oracle DDL (quoted table/columns, index, synonym)."""
    qualified = f'"{schema}"."{table}"'
    return [
        f"""CREATE TABLE {qualified} (
            "installed_rank" INT NOT NULL,
            "version" VARCHAR2(50),
            "description" VARCHAR2(200) NOT NULL,
            "type" VARCHAR2(20) NOT NULL,
            "script" VARCHAR2(1000) NOT NULL,
            "checksum" INT,
            "installed_by" VARCHAR2(100) NOT NULL,
            "installed_on" TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            "execution_time" INT NOT NULL,
            "success" NUMBER(1) NOT NULL,
            CONSTRAINT "{table}_pk" PRIMARY KEY ("installed_rank")
        )""",
        f'CREATE INDEX "{schema}"."{table}_s_idx" ON {qualified} ("success")',
        f'CREATE SYNONYM "{schema}".{table} FOR {qualified}',
    ]


def _uppercase_ddl(schema, table):
    return [f"""CREATE TABLE "{schema}".{table} (
            installed_rank INT NOT NULL PRIMARY KEY, version VARCHAR2(50),
            description VARCHAR2(200) NOT NULL, type VARCHAR2(20) NOT NULL,
            script VARCHAR2(1000) NOT NULL, checksum INT,
            installed_by VARCHAR2(100) NOT NULL,
            installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            execution_time INT NOT NULL, success NUMBER(1) NOT NULL
        )"""]


def _seed(schema, table, quoted):
    target = f'"{schema}"."{table}"' if quoted else f'"{schema}".{table}'
    cols = [
        "installed_rank",
        "version",
        "description",
        "type",
        "script",
        "checksum",
        "installed_by",
        "installed_on",
        "execution_time",
        "success",
    ]
    column_list = ", ".join(f'"{c}"' if quoted else c for c in cols)
    insert = f"INSERT INTO {target} ({column_list}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    return [
        (insert, [1, "1", "init", "SQL", "V1__init.sql", 111, "flyway", SUCCESS_ON, 10, 1]),
        (insert, [2, "2", "broken", "SQL", "V2__broken.sql", 222, "flyway", FAILED_ON, 20, 0]),
        # Flyway records a repeatable migration as a versionless SQL row.
        (insert, [3, None, "view", "SQL", "R__view.sql", 333, "flyway", SUCCESS_ON, 5, 1]),
    ]


@pytest.fixture
def oracle_schema():
    admin = ProviderRegistry.create_provider(_config())
    admin.create_connection()
    schema = f"FIX_ORAFLY_{uuid.uuid4().hex[:8].upper()}"
    admin.execute_statement(f'CREATE USER "{schema}" IDENTIFIED BY "Fix0rafly1"')
    admin.execute_statement(f'ALTER USER "{schema}" QUOTA UNLIMITED ON USERS')
    admin.execute_statement(f'GRANT CREATE SESSION, CREATE TABLE TO "{schema}"')
    try:
        yield admin, schema
    finally:
        admin.execute_statement(f'DROP USER "{schema}" CASCADE')
        admin.close()


@pytest.mark.parametrize(
    ("table", "ddl", "quoted", "flyway_table"),
    [
        ("flyway_schema_history", _flyway_ddl, True, "flyway_schema_history"),
        ("FLYWAY_SCHEMA_HISTORY", _uppercase_ddl, False, "flyway_schema_history"),
        ("legacy_history", _flyway_ddl, True, "legacy_history"),
    ],
    ids=["flyway-quoted-lowercase", "unquoted-uppercase", "configured-name"],
)
def test_import_flyway_reads_history_table_shape(
    oracle_schema, tmp_path, table, ddl, quoted, flyway_table
):
    admin, schema = oracle_schema
    for statement in ddl(schema, table):
        admin.execute_statement(statement)
    for statement, params in _seed(schema, table, quoted):
        admin.execute_statement(statement, params=params)
    admin.commit_transaction()

    client = DBLiftClient.from_config(_config(schema), migrations_dir=tmp_path)
    try:
        result = client.import_flyway(flyway_table=flyway_table)
        assert result.success, result.error_message
        assert "3 entries imported" in result.message
    finally:
        client.close()

    rows = sorted(admin.get_applied_migrations(schema), key=lambda r: r["installed_rank"])
    assert [r["script"] for r in rows] == ["V1__init.sql", "V2__broken.sql", "R__view.sql"]
    assert [r["type"] for r in rows] == ["SQL", "SQL", "REPEATABLE"]
    assert [r["success"] for r in rows] == [True, False, True]
    assert [r["installed_on"] for r in rows] == [SUCCESS_ON, FAILED_ON, SUCCESS_ON]

    if flyway_table == "flyway_schema_history":
        # The Flyway compatibility check reads the same source table.
        snapshot = MigrationHistoryManager(
            admin, schema, "tester", NullLog()
        ).collect_flyway_compatibility_snapshot()
        assert snapshot.collection_error == ""
        assert snapshot.flyway_exists and snapshot.dblift_exists
        assert [r["script"] for r in snapshot.flyway_migrations] == [
            "V1__init.sql",
            "V2__broken.sql",
            "R__view.sql",
        ]
        assert [r["script"] for r in snapshot.dblift_migrations] == [
            "V1__init.sql",
            "V2__broken.sql",
            "R__view.sql",
        ]
        verdict = validate_flyway_compatibility(snapshot)
        assert verdict["compatible"] is True, verdict["error_message"]
