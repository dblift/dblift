"""A lowercase ``schema:`` value resolves to the uppercase Oracle user.

Oracle uppercases unquoted identifiers, so ``CREATE USER myschema`` creates
``MYSCHEMA``. dblift used to quote the raw config value — ``ALTER SESSION SET
CURRENT_SCHEMA = "myschema"`` — which fails ORA-01435 "user does not exist"
against that very account. The provider now upper-cases the schema, as it does
object names, so a natural lowercase spelling works.

Prerequisites: an Oracle instance reachable at localhost:1521, service
FREEPDB1, connectable as ``system`` / ``oracle`` (the container fixture's
credentials).
"""

import uuid

import pytest

from dblift.config.dblift_config import DbliftConfig
from dblift.db.plugins.oracle.config import OracleConfig
from dblift.db.provider_registry import ProviderRegistry

pytestmark = [pytest.mark.integration, pytest.mark.oracle]

HOST = "localhost"
PORT = 1521
SERVICE = "FREEPDB1"
ADMIN_USER = "system"
ADMIN_PASSWORD = "oracle"


def _admin_config() -> DbliftConfig:
    return DbliftConfig(
        database=OracleConfig(
            type="oracle",
            host=HOST,
            port=PORT,
            service_name=SERVICE,
            username=ADMIN_USER,
            password=ADMIN_PASSWORD,
        )
    )


def test_lowercase_schema_resolves_to_the_uppercase_oracle_user():
    schema = f"mcpt_ora_{uuid.uuid4().hex[:8]}"  # lowercase, as a user might write it
    admin = ProviderRegistry.create_provider(_admin_config())
    admin.create_connection()
    try:
        admin.execute_statement(f"CREATE USER {schema.upper()} IDENTIFIED BY Pw123456")
        admin.execute_statement(f"GRANT CREATE SESSION TO {schema.upper()}")

        # A provider configured with the lowercase spelling.
        cfg = DbliftConfig(
            database=OracleConfig(
                type="oracle",
                host=HOST,
                port=PORT,
                service_name=SERVICE,
                username=ADMIN_USER,
                password=ADMIN_PASSWORD,
                schema=schema,
            )
        )
        provider = ProviderRegistry.create_provider(cfg)
        provider.create_connection()
        try:
            # Would raise ORA-01435 before the fix (quoted lowercase).
            provider.set_current_schema(schema)
            rows = provider.execute_query(
                "SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS s FROM dual"
            )
            current = rows[0]["s"] if isinstance(rows[0], dict) else rows[0][0]
            assert current == schema.upper()
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
    finally:
        admin.execute_statement(f"DROP USER {schema.upper()} CASCADE")
        close = getattr(admin, "close", None)
        if callable(close):
            close()
