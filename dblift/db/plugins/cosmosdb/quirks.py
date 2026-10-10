"""CosmosDB :class:`DialectQuirks`."""

from __future__ import annotations

from typing import Dict, Optional

from dblift.db.base_quirks import BaseQuirks


class CosmosdbQuirks(BaseQuirks):
    """Azure Cosmos DB-specific :class:`DialectQuirks` for the NoSQL dialect.

    Covers Cosmos DB's deviations from relational SQL: ``is_nosql=True``
    (no relational DDL, no transactions), schemaless containers
    (``schema_required=False``), bare JSON keys instead of quoted SQL
    identifiers, Python-only migrations
    (``supports_sql_migrations=False``), no traditional username/password
    auth, and indexes managed outside SQL DDL via the Cosmos indexing
    policy.
    """

    # Capability matrix (was ``_CAPABILITIES["cosmosdb"]``).
    supports_transactions = False
    supports_transactional_ddl = False
    schema_required = False  # schemaless, no concept
    uppercase_identifiers = False
    clean_strategy = "native"
    default_schema_name = "default"
    boolean_false_literal = "false"
    is_nosql = True
    # Cosmos containers are created and reshaped through the Azure SDK, so
    # migrations are Python scripts (``migrate(context)``) rather than SQL.
    supports_sql_migrations = False
    # https://learn.microsoft.com/en-us/cosmos-db/query/overview
    # Azure account auth (endpoint + key, or managed identity) instead of
    # host/user/password. Gates the auth validation in
    # ``DbliftConfig.validate_complete_data``.
    requires_cloud_account_auth = True
    # NoSQL: identifiers are JSON keys, not SQL identifiers — no quoting.
    quote_open = ""
    quote_close = ""
    # Wave B hooks.
    native_driver_display = "Azure Cosmos DB SDK for Python"
    requires_credentials = False
    # No validate-sql offline lint: ``parser_class()`` below returns None for
    # every parser_type because Cosmos DB has no SQL for dblift to read, so a
    # placeholder connection would not unlock anything. ``lint_placeholder_url``
    # stays unset (``None``, from BaseQuirks).
    connection_identifier_attrs = ("url", "account_endpoint")
    missing_connection_identifier_hint = (
        "CosmosDB account endpoint not specified (set database.account_endpoint "
        "in the config file or use --db-url with a cosmos endpoint)."
    )

    def __init__(self, dialect_name: str = "cosmosdb") -> None:
        """Initialize Cosmos DB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """No parser — Cosmos has no SQL for dblift to read.

        The dedicated regex parser existed to read the pseudo-DDL
        (``CREATE CONTAINER``, ``SET THROUGHPUT``, …) that the SDK
        translator executed; both are gone, and ``HybridParser`` cannot
        stand in because it falls back to that same regex parser. Cosmos
        migrations are Python, and read-side queries are native Cosmos SQL
        executed verbatim — never parsed into a schema model. Asking for a
        parser is therefore an error, not a silent degradation.
        """
        return None

    def type_equivalents(self) -> "Dict[str, str]":
        """CosmosDB has no relational type aliases — JSON documents store untyped values."""
        return {}


__all__ = ["CosmosdbQuirks"]
