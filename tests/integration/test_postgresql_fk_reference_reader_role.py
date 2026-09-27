"""Prove the drop-column safety check's PostgreSQL queries actually execute,
and that a read-only role sees what they find.

``PostgresqlQuirks.fk_reference_query`` and ``index_reference_query`` return
``(sql, params)`` for the queries a drop-column safety check runs before
rendering a ``DROP COLUMN``: which foreign keys reference the column, and
which indexes cover it. Both previously hardcoded PostgreSQL's raw
``$1``/``$2``/``$3`` wire placeholders directly in the SQL text; the
PostgreSQL driver in this repository is psycopg, whose paramstyle only binds
dblift's own ``?`` convention (translated by the provider), so neither query
could execute through the provider at all. ``fk_reference_query`` also read
``information_schema``, which PostgreSQL hides from a role holding only
``SELECT`` -- so even once the placeholders bind, the safety check would
silently miss a referencing key under such a role.

This test runs both queries through ``provider.execute_query(sql, params)``,
once as the schema owner and once as a ``USAGE``+``SELECT`` reader role, and
asserts both see the same three referencing foreign keys (not an unrelated
one) and the same covering index (not a same-table index that does not cover
the column).
"""

from __future__ import annotations

import uuid

import pytest

from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.integration


def _config(schema: str, username: str, password: str) -> DbliftConfig:
    database = PostgreSqlConfig(
        type="postgresql",
        host="localhost",
        port=5432,
        database="testdb",
        username=username,
        password=password,
        schema=schema,
    )
    return DbliftConfig(database=database)


def test_fk_and_index_reference_queries_execute_and_are_visible_to_a_reader():
    schema = f"fk_ref_{uuid.uuid4().hex[:8]}"
    other_schema = f"fk_ref_other_{uuid.uuid4().hex[:8]}"
    role = f"fk_ref_reader_{uuid.uuid4().hex[:8]}"
    password = "ReaderPass123"

    admin = ProviderRegistry.create_provider(_config(schema, "postgres", "postgres"))
    admin.create_connection()
    reader = None
    try:
        admin.execute_statement(f'CREATE SCHEMA "{schema}"')
        admin.execute_statement(f'CREATE SCHEMA "{other_schema}"')
        admin.execute_statement(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
        admin.execute_statement(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        admin.execute_statement(f'GRANT USAGE ON SCHEMA "{other_schema}" TO "{role}"')

        # parent: PK on id, separate UNIQUE on code, plus a composite UNIQUE
        # on (code, id) so a composite FK can reference id as its *second*
        # column. Two indexes: the auto UNIQUE index on code alone (must NOT
        # show up when checking references to id) and an explicit composite
        # index on (code, id) (must show up).
        admin.execute_statement(
            f'CREATE TABLE "{schema}".parent (id INTEGER PRIMARY KEY, code TEXT UNIQUE)'
        )
        admin.execute_statement(
            f'ALTER TABLE "{schema}".parent ' f"ADD CONSTRAINT parent_code_id_key UNIQUE (code, id)"
        )
        admin.execute_statement(f'CREATE INDEX ix_parent_code_id ON "{schema}".parent (code, id)')

        # child_a: single-column FK on parent.id.
        admin.execute_statement(
            f'CREATE TABLE "{schema}".child_a '
            f'(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES "{schema}".parent(id))'
        )
        # child_b: composite FK on (parent.code, parent.id) -- id is the
        # *second* referenced column.
        admin.execute_statement(
            f'CREATE TABLE "{schema}".child_b ('
            f"id INTEGER PRIMARY KEY, parent_code TEXT, parent_id INTEGER, "
            f'FOREIGN KEY (parent_code, parent_id) REFERENCES "{schema}".parent(code, id))'
        )
        # child_c: FK to an unrelated table -- must not appear.
        admin.execute_statement(f'CREATE TABLE "{schema}".other (id INTEGER PRIMARY KEY)')
        admin.execute_statement(
            f'CREATE TABLE "{schema}".child_c '
            f'(id INTEGER PRIMARY KEY, other_id INTEGER REFERENCES "{schema}".other(id))'
        )
        # child_d: FK from a different schema -- must appear, schema-qualified.
        admin.execute_statement(
            f'CREATE TABLE "{other_schema}".child_d '
            f'(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES "{schema}".parent(id))'
        )

        admin.execute_statement(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"')
        admin.execute_statement(
            f'GRANT SELECT ON ALL TABLES IN SCHEMA "{other_schema}" TO "{role}"'
        )

        reader = ProviderRegistry.create_provider(_config(schema, role, password))
        reader.create_connection()

        quirks = PostgresqlQuirks()

        for provider, label in ((admin, "owner"), (reader, "reader")):
            fk_sql, fk_params = quirks.fk_reference_query(schema, "parent", "id")
            fk_rows = provider.execute_query(fk_sql, fk_params)
            fk_tables = {row["table_name"] for row in fk_rows}
            assert fk_tables == {
                f"{schema}.child_a",
                f"{schema}.child_b",
                f"{other_schema}.child_d",
            }, f"{label}: fk_reference_query returned {fk_tables!r}"

            index_sql, index_params = quirks.index_reference_query(schema, "parent", "id")
            index_rows = provider.execute_query(index_sql, index_params)
            index_names = {row["index_name"] for row in index_rows}
            assert (
                "ix_parent_code_id" in index_names
            ), f"{label}: index_reference_query missed the covering index: {index_names!r}"
            assert (
                "parent_code_key" not in index_names
            ), f"{label}: index_reference_query returned the code-only index: {index_names!r}"
    finally:
        try:
            if reader is not None:
                reader.close()
        finally:
            try:
                # A query raised mid-test (e.g. today's $n placeholder
                # mismatch) leaves the admin connection's implicit
                # transaction aborted; roll it back before the cleanup DDL.
                admin.rollback_transaction()
                admin.execute_statement(f'DROP SCHEMA IF EXISTS "{other_schema}" CASCADE')
                admin.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                admin.execute_statement(f'DROP OWNED BY "{role}"')
                admin.execute_statement(f'DROP ROLE IF EXISTS "{role}"')
            finally:
                admin.close()
