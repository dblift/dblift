"""A lowercase ``schema:`` value resolves consistently across the whole
Oracle admin flow: create, connect and catalog lookup.

Oracle uppercases unquoted identifiers, so ``CREATE USER myschema`` creates
``MYSCHEMA``. The provider now normalizes the schema the same way at every
site that uses it against the database — ``create_schema_if_not_exists``,
``set_current_schema`` and the catalog lookups (``table_exists`` among them)
— so a lowercase config value creates, connects to and finds objects in the
same uppercase user throughout. Before the fix, ``create_schema_if_not_exists``
created a *lowercase* user (it quoted the raw value verbatim) while
``set_current_schema`` upper-cased it, so the two could never agree: the
create step produced a user the connect step could not find (ORA-01435).

Prerequisites: an Oracle instance reachable at localhost:1521, service
FREEPDB1, connectable as ``system`` / ``oracle`` (the container fixture's
credentials).
"""

import uuid
from typing import Any, List

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


def _scalar(rows: List[Any]) -> Any:
    """Return the single column of the single row of an Oracle query result."""
    row = rows[0]
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def _user_count(provider: Any, username: str) -> int:
    rows = provider.execute_query(
        "SELECT COUNT(*) AS c FROM ALL_USERS WHERE username = ?", [username]
    )
    return int(_scalar(rows))


def test_lowercase_schema_is_consistent_across_create_connect_and_lookup():
    """The create -> connect -> lookup flow a real migration drives, all
    exercised for one lowercase ``schema:`` value on a single admin
    connection (no separate per-user login needed: every method here just
    targets the named schema over the admin session)."""
    schema = f"mcpt_ora_{uuid.uuid4().hex[:8]}"  # lowercase, as a user might write it
    schema_upper = schema.upper()
    table = "PROBE_TBL"

    provider = ProviderRegistry.create_provider(_admin_config())
    provider.create_connection()
    try:
        # Would have created a LOWERCASE user before the fix, which
        # set_current_schema below could then never find (ORA-01435).
        provider.create_schema_if_not_exists(schema)

        assert _user_count(provider, schema_upper) == 1, f"expected one {schema_upper} user"
        assert _user_count(provider, schema) == 0, f"stray lowercase user {schema} was created"

        provider.set_current_schema(schema)
        current = _scalar(
            provider.execute_query("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS s FROM dual")
        )
        assert current == schema_upper

        provider.execute_statement(f'CREATE TABLE "{schema_upper}"."{table}" (id NUMBER)')
        try:
            assert provider.table_exists(schema, table) is True
        finally:
            provider.execute_statement(f'DROP TABLE "{schema_upper}"."{table}" PURGE')
    finally:
        provider.execute_statement(f'DROP USER "{schema_upper}" CASCADE')
        assert _user_count(provider, schema_upper) == 0, "stray Oracle user left behind"
        assert _user_count(provider, schema) == 0, "stray Oracle user left behind"
        close = getattr(provider, "close", None)
        if callable(close):
            close()
