"""Cross-schema introspection must not fan out (P7).

Bug this guards against:
  * d88f88a4 BUG-01 — PostgreSQL ``get_sequences_query()`` joined ``pg_sequences``
    against ``pg_class`` without constraining ``ps.schemaname = n.nspname``,
    causing 2-3× duplicate rows when the same sequence name existed in
    multiple schemas.
  * Oracle schema-quoting family (5f8baf92, 604d2335, bd364181) — same
    shape: queries that forgot to filter by target schema.

Doctrine: introspection of schema X must return exactly the objects in
schema X, never objects from other schemas with the same name. This file
creates the duplicate-name scenario and asserts no fan-out.

PostgreSQL-only — SQLite has no schemas, MySQL's ``schema`` == ``database``,
so the bug pattern is specific to dialects with first-class schemas.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]


@pytest.mark.parametrize("db_container", ["postgresql"], indirect=True)
def test_sequence_introspection_no_cross_schema_fanout(db_container, tmp_path):
    """Create a sequence with the same name in two schemas → introspection returns 1, not 2."""
    from db.provider_registry import ProviderRegistry
    from tests.integration.helpers.migration_helper import create_config

    config_file = create_config(tmp_path, db_container)

    from config.dblift_config import load_config

    config = load_config(str(config_file))

    provider_cls = ProviderRegistry.get_provider_class(config.database.type)
    provider = provider_cls(config, log=None)  # NullLog fallback

    # Create two schemas, each with a sequence of the same name.
    provider.execute_statement("CREATE SCHEMA IF NOT EXISTS scm_a")
    provider.execute_statement("CREATE SCHEMA IF NOT EXISTS scm_b")
    provider.execute_statement("CREATE SEQUENCE scm_a.shared_seq START 1")
    provider.execute_statement("CREATE SEQUENCE scm_b.shared_seq START 1")

    try:
        # Introspect schema scm_a — we must see 1 sequence, not 2.
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        sequences = introspector.get_sequences("scm_a")

        names = [s.name for s in sequences]
        shared = [n for n in names if n == "shared_seq"]
        assert len(shared) == 1, (
            f"Cross-schema fan-out: get_sequences('scm_a') returned "
            f"{len(shared)} rows for 'shared_seq' (expected 1). All names: {names}"
        )
    finally:
        provider.execute_statement("DROP SCHEMA scm_a CASCADE")
        provider.execute_statement("DROP SCHEMA scm_b CASCADE")
