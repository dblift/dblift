"""Live DB2 regression: ``import-flyway`` reads the table Flyway creates.

Flyway's DB2 support creates its history table as a quoted lowercase name
with quoted lowercase columns (``"flyway_schema_history"``,
``"installed_rank"``, ...), see ``DB2Database.getRawCreateScript`` in
flyway/flyway. The import must read that shape, a hand-built uppercase
table, and a configured table name.

Opt-in: set DBLIFT_TEST_DB2_URL, DBLIFT_TEST_DB2_USER,
DBLIFT_TEST_DB2_PASSWORD and DBLIFT_TEST_DB2_SCHEMA (an uppercase schema the
user owns). Tables are created and dropped by each test.
"""

import datetime
import os

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.db.plugins.db2.config import Db2Config
from dblift.db.plugins.db2.provider import Db2Provider

pytestmark = [pytest.mark.integration]

SUCCESS_ON = datetime.datetime(2024, 1, 2, 3, 4, 5)
FAILED_ON = datetime.datetime(2024, 1, 3, 4, 5, 6)
COLUMNS = [
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


def _config():
    url = os.environ.get("DBLIFT_TEST_DB2_URL")
    if not url:
        pytest.skip("Set DBLIFT_TEST_DB2_URL to run the DB2 import-flyway test")
    return DbliftConfig(
        database=Db2Config(
            type="db2",
            url=url,
            username=os.environ.get("DBLIFT_TEST_DB2_USER"),
            password=os.environ.get("DBLIFT_TEST_DB2_PASSWORD"),
            schema=os.environ.get("DBLIFT_TEST_DB2_SCHEMA", "DBLIFT_TEST"),
        )
    )


def _flyway_ddl(schema, table):
    """Flyway's own DB2 DDL (quoted table/columns, check, primary key, index)."""
    qualified = f'"{schema}"."{table}"'
    return [
        f"""CREATE TABLE {qualified} (
            "installed_rank" INT NOT NULL,
            "version" VARCHAR(50),
            "description" VARCHAR(200) NOT NULL,
            "type" VARCHAR(20) NOT NULL,
            "script" VARCHAR(1000) NOT NULL,
            "checksum" INT,
            "installed_by" VARCHAR(100) NOT NULL,
            "installed_on" TIMESTAMP DEFAULT CURRENT TIMESTAMP NOT NULL,
            "execution_time" INT NOT NULL,
            "success" SMALLINT NOT NULL,
            CONSTRAINT "{table}_s" CHECK ("success" in(0,1))
        )""",
        f'ALTER TABLE {qualified} ADD CONSTRAINT "{table}_pk" PRIMARY KEY ("installed_rank")',
        f'CREATE INDEX "{schema}"."{table}_s_idx" ON {qualified} ("success")',
    ]


def _uppercase_ddl(schema, table):
    return [f"""CREATE TABLE "{schema}".{table} (
            installed_rank INT NOT NULL PRIMARY KEY, version VARCHAR(50),
            description VARCHAR(200) NOT NULL, type VARCHAR(20) NOT NULL,
            script VARCHAR(1000) NOT NULL, checksum INT,
            installed_by VARCHAR(100) NOT NULL,
            installed_on TIMESTAMP DEFAULT CURRENT TIMESTAMP NOT NULL,
            execution_time INT NOT NULL, success SMALLINT NOT NULL
        )"""]


def _seed(schema, table, quoted):
    target = f'"{schema}"."{table}"' if quoted else f'"{schema}".{table}'
    column_list = ", ".join(f'"{c}"' if quoted else c for c in COLUMNS)
    insert = f"INSERT INTO {target} ({column_list}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    return [
        (insert, [1, "1", "init", "SQL", "V1__init.sql", 111, "flyway", SUCCESS_ON, 10, 1]),
        (insert, [2, "2", "broken", "SQL", "V2__broken.sql", 222, "flyway", FAILED_ON, 20, 0]),
    ]


@pytest.fixture
def db2_provider():
    config = _config()
    provider = Db2Provider(config, NullLog())
    schema = config.database.schema
    created = []
    try:
        yield provider, schema, config, created
    finally:
        for table in created + ["DBLIFT_SCHEMA_HISTORY", "DBLIFT_MIGRATION_LOCK"]:
            if provider.table_exists(schema, f'"{table}"'):
                provider.execute_statement(f'DROP TABLE "{schema}"."{table}"')
        provider.commit_transaction()
        provider.close()


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
    db2_provider, tmp_path, table, ddl, quoted, flyway_table
):
    provider, schema, config, created = db2_provider
    created.append(table)
    for statement in ddl(schema, table):
        provider.execute_statement(statement)
    for statement, params in _seed(schema, table, quoted):
        provider.execute_statement(statement, params=params)
    provider.commit_transaction()

    client = DBLiftClient.from_config(config, migrations_dir=tmp_path)
    try:
        result = client.import_flyway(flyway_table=flyway_table)
        assert result.success, result.error_message
        assert "2 entries imported" in result.message
    finally:
        client.close()

    rows = sorted(provider.get_applied_migrations(schema), key=lambda r: r["installed_rank"])
    assert [r["script"] for r in rows] == ["V1__init.sql", "V2__broken.sql"]
    assert [r["success"] for r in rows] == [True, False]
    assert [r["installed_on"] for r in rows] == [SUCCESS_ON, FAILED_ON]

    if flyway_table == "flyway_schema_history":
        # The Flyway compatibility check reads the same source table.
        snapshot = MigrationHistoryManager(
            provider, schema, "tester", NullLog()
        ).collect_flyway_compatibility_snapshot()
        assert snapshot.collection_error == ""
        assert snapshot.flyway_exists and snapshot.dblift_exists
        assert [r["script"] for r in snapshot.flyway_migrations] == [
            "V1__init.sql",
            "V2__broken.sql",
        ]
