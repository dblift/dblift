"""A DBLiftClient stays usable after a schema-history preflight failure.

On PostgreSQL a failed ``CREATE TABLE`` for the history table aborts the
connection's transaction. Preflight rolls it back before reporting the
failure, so later commands on the same client run normally: a dry-run
migrate lists the pending script, and ``clean`` reports its real result
instead of finding nothing to drop on an unusable connection.
"""

from __future__ import annotations

import uuid

import pytest

from dblift.api.client import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.integration


def _admin_config(schema: str) -> DbliftConfig:
    database = PostgreSqlConfig(
        type="postgresql",
        host="localhost",
        port=5432,
        database="testdb",
        username="postgres",
        password="postgres",
        schema=schema,
    )
    return DbliftConfig(database=database)


def test_client_is_reusable_after_history_table_preflight_failure(tmp_path):
    schema = f"fix_preflight2_{uuid.uuid4().hex[:8]}"
    role = f"fix_preflight2_role_{uuid.uuid4().hex[:8]}"
    password = "ReusePass123"

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t1 (id INTEGER);\n", encoding="utf-8")

    admin = ProviderRegistry.create_provider(_admin_config(schema))
    admin.create_connection()
    client = None
    try:
        admin.execute_statement(f'CREATE SCHEMA "{schema}"')
        admin.execute_statement(f'CREATE TABLE "{schema}".owned_by_admin (id INTEGER)')
        admin.execute_statement(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
        # USAGE only: the role can read the schema but not create the
        # history table, and cannot drop the admin's table.
        admin.execute_statement(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')

        client = DBLiftClient.from_config(
            DbliftConfig.from_dict(
                {
                    "database": {
                        "url": f"postgresql://{role}:{password}@localhost:5432/testdb",
                        "schema": schema,
                    },
                    "migrations": {"directory": str(migrations)},
                }
            )
        )

        info = client.info()
        assert info.success is False
        assert info.error_message.startswith("Could not create the schema-history table: ")

        dry = client.migrate(dry_run=True)
        assert dry.success is True, dry.error_message
        assert "InFailedSqlTransaction" not in (dry.error_message or "")

        client.info()
        cleaned = client.clean(clean_enabled=True)
        assert cleaned.success is False
        assert "must be owner" in (cleaned.error_message or "") + " ".join(
            getattr(cleaned, "warnings", []) or []
        )

        admin.execute_statement(f'GRANT CREATE ON SCHEMA "{schema}" TO "{role}"')
        migrated = client.migrate()
        assert migrated.success is True, migrated.error_message
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            try:
                admin.rollback_transaction()
                admin.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                admin.execute_statement(f'DROP OWNED BY "{role}"')
                admin.execute_statement(f'DROP ROLE IF EXISTS "{role}"')
            finally:
                admin.close()


def test_unreadable_history_reports_the_read_error_and_client_stays_usable(tmp_path):
    """A failed history read aborts the transaction; the real error must surface."""
    schema = f"fix_hist_read_{uuid.uuid4().hex[:8]}"
    role = f"fix_hist_read_role_{uuid.uuid4().hex[:8]}"
    password = "ReadPass123"

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t1 (id INTEGER);\n", encoding="utf-8")

    admin = ProviderRegistry.create_provider(_admin_config(schema))
    admin.create_connection()
    client = None
    try:
        admin.execute_statement(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
        admin.execute_statement(f'CREATE SCHEMA "{schema}" AUTHORIZATION "{role}"')

        client = DBLiftClient.from_config(
            DbliftConfig.from_dict(
                {
                    "database": {
                        "url": f"postgresql://{role}:{password}@localhost:5432/testdb",
                        "schema": schema,
                    },
                    "migrations": {"directory": str(migrations)},
                }
            )
        )
        assert client.migrate().success is True
        (migrations / "V2__next.sql").write_text(
            "CREATE TABLE t2 (id INTEGER);\n", encoding="utf-8"
        )

        admin.execute_statement(f'REVOKE SELECT ON "{schema}".dblift_schema_history FROM "{role}"')
        for result in (client.info(), client.validate(), client.migrate(dry_run=True)):
            assert result.success is False
            assert "permission denied for table dblift_schema_history" in result.error_message
            assert "InFailedSqlTransaction" not in result.error_message

        admin.execute_statement(f'GRANT SELECT ON "{schema}".dblift_schema_history TO "{role}"')
        assert client.info().success is True
        assert client.validate().success is True
        dry = client.migrate(dry_run=True)
        assert dry.success is True, dry.error_message
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            try:
                admin.rollback_transaction()
                admin.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                admin.execute_statement(f'DROP OWNED BY "{role}"')
                admin.execute_statement(f'DROP ROLE IF EXISTS "{role}"')
            finally:
                admin.close()
