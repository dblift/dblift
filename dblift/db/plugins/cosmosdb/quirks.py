"""CosmosDB :class:`DialectQuirks` — Epic 26."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Type

from dblift.db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from dblift.core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from dblift.core.sql_generator.base_generator import BaseSqlGenerator


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

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """No SQL-DDL generator — Cosmos containers are created through the Azure SDK."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """ALTER generator is supplied by an installed extension package."""
        return None

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

    # Story 26-3: CosmosDB has no SQL DDL, so every "DROP X" form renders as
    # an explanatory comment. Centralised here so ``sql_generator.py`` no
    # longer carries ``if dialect == "cosmosdb"`` branches.
    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """Render every DROP form as an explanatory comment.

        Nothing Cosmos drops is expressible in SQL: containers go through
        ``database.delete_container`` and the remaining object types do not
        exist in the NoSQL API. Emitting a comment keeps generated scripts
        readable without pretending a statement is runnable.
        """
        if obj_type in ("VIEW", "MATERIALIZED_VIEW"):
            return f"-- CosmosDB does not support views. No DROP VIEW needed for '{obj_name}'."
        if obj_type == "TABLE":
            return (
                f"-- CosmosDB containers are dropped through the Azure SDK, not SQL.\n"
                f"-- In a Python migration: "
                f"context.db.delete_container({obj_name!r})"
            )
        if obj_type == "INDEX":
            return (
                "-- CosmosDB indexes are managed via indexing policy, not SQL DDL.\n"
                "-- To modify indexes, update the container's indexing policy via Azure SDK."
            )
        if obj_type == "SEQUENCE":
            return (
                f"-- CosmosDB does not support sequences. "
                f"No DROP SEQUENCE needed for '{obj_name}'."
            )
        if obj_type in ("PROCEDURE", "FUNCTION"):
            return (
                "-- CosmosDB SQL API does not support stored procedures/functions.\n"
                "-- Use Azure Functions or stored procedures via other APIs if needed."
            )
        if obj_type == "TRIGGER":
            return (
                f"-- CosmosDB does not support triggers. "
                f"No DROP TRIGGER needed for '{obj_name}'."
            )
        if obj_type == "EXTENSION":
            return (
                f"-- CosmosDB does not support extensions. "
                f"No DROP EXTENSION needed for '{obj_name}'."
            )
        # Unknown type: still emit a comment rather than invalid SQL.
        return (
            f"-- CosmosDB does not support DROP {obj_type} via SQL API "
            f"for '{obj_name}'.\n"
            "-- This operation may need to be performed via Azure SDK or Portal."
        )

    def skip_index_ddl(self) -> bool:
        """True — CosmosDB indexing policy is JSON metadata managed via the SDK, not SQL DDL."""
        # Indexing policy is JSON metadata managed via the SDK, not SQL.
        return True

    def skip_index_ddl_comment(self) -> str:
        """Emit a CosmosDB-specific comment pointing users at the Azure SDK indexing-policy API."""
        return (
            "-- CosmosDB indexes are managed via indexing policy, not SQL DDL.\n"
            "-- To modify indexes, update the container's indexing policy via Azure SDK."
        )

    # Column ALTER hooks — CosmosDB is schema-less; return comment statements.
    def _cosmosdb_noop(
        self, formatted_table: str, formatted_column: str, change_kind: str, dialect: str
    ) -> object:
        from dblift.core.sql_generator.sql_statement import SqlStatement

        sql = (
            f"-- CosmosDB is schema-less, no ALTER TABLE needed for "
            f"{formatted_table}.{formatted_column} {change_kind} change"
        )
        return SqlStatement(
            sql=sql,
            statement_type="COMMENT",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def render_column_nullable_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """Schema-less — emit a no-op comment rather than an ALTER for nullable changes."""
        return self._cosmosdb_noop(formatted_table, formatted_column, "nullable", dialect)

    def render_column_default_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """Schema-less — emit a no-op comment rather than an ALTER for default changes."""
        return self._cosmosdb_noop(formatted_table, formatted_column, "default", dialect)

    def render_column_type_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """Schema-less — emit a no-op comment rather than an ALTER for type changes."""
        return self._cosmosdb_noop(formatted_table, formatted_column, "type", dialect)

    def render_column_collation_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """Schema-less — emit a no-op comment rather than an ALTER for collation changes."""
        return self._cosmosdb_noop(formatted_table, formatted_column, "collation", dialect)

    def introspector_class(self) -> "Optional[Type[Any]]":
        """CosmosDB rich introspection is supplied by an installed extension package."""
        return None

    def type_equivalents(self) -> "Dict[str, str]":
        """CosmosDB has no relational type aliases — JSON documents store untyped values."""
        return {}

    def type_preferences(self) -> "Dict[str, str]":
        """CosmosDB has no preferred SQL types — values are JSON-typed at the document level."""
        return {}


__all__ = ["CosmosdbQuirks"]
