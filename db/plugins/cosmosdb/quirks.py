"""CosmosDB :class:`DialectQuirks` — Epic 26."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from db.base_quirks import BaseQuirks


class CosmosdbQuirks(BaseQuirks):
    """Azure Cosmos DB-specific :class:`DialectQuirks` for the NoSQL dialect.

    Covers Cosmos DB's deviations from relational SQL: ``is_nosql=True``
    (no relational DDL, no transactions), schemaless containers
    (``schema_required=False``), bare JSON keys instead of quoted SQL
    identifiers, ``CREATE CONTAINER`` rather than ``CREATE TABLE``,
    DROP statements that route through the Azure SDK rather than SQL execution
    (``requires_sdk_for_drop=True``), no traditional username/password
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
    # NoSQL: identifiers are JSON keys, not SQL identifiers — no quoting.
    quote_open = ""
    quote_close = ""
    # Table DDL (story 26-5). CosmosDB uses CREATE CONTAINER.
    table_create_keyword = "CONTAINER"
    # Wave B hooks.
    native_driver_display = "Azure Cosmos DB SDK for Python"
    requires_credentials = False
    connection_identifier_attrs = ("url", "account_endpoint")
    missing_connection_identifier_hint = (
        "CosmosDB account endpoint not specified (set database.account_endpoint "
        "in the config file or use --db-url with a cosmos endpoint)."
    )

    def __init__(self, dialect_name: str = "cosmosdb") -> None:
        """Initialize Cosmos DB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """CosmosDB parser dispatch: hybrid → :class:`HybridParser`, regex →
        :class:`CosmosDbRegexParser`, sqlglot → ``None`` (no Cosmos sqlglot dialect)."""
        # CosmosDB: legacy ``SQLGLOT_PARSER_MAP`` omitted cosmosdb, so
        # ``"sqlglot"`` returns None (factory raises). Hybrid uses
        # HybridParser (CosmosDB SQL is T-SQL-like enough).
        if parser_type == "hybrid":
            from core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "regex":
            from db.plugins.cosmosdb.parser.cosmosdb_regex_parser import (
                CosmosDbRegexParser,
            )

            return CosmosDbRegexParser
        return None

    # CosmosDB has no SQL DDL — most "DROP X" forms become explanatory
    # comments or pseudo-SQL the SDK translator rewrites into Azure SDK calls.
    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """Render DROP forms: ``DROP CONTAINER`` (SDK-routed) or explanatory comment.

        Tables become ``DROP CONTAINER`` (the SDK translator turns this into an
        ``delete_container`` SDK call); everything else (views, indexes, sequences,
        procedures, triggers, extensions) becomes a comment since CosmosDB's NoSQL
        API doesn't support those constructs.
        """
        if obj_type in ("VIEW", "MATERIALIZED_VIEW"):
            return f"-- CosmosDB does not support views. No DROP VIEW needed for '{obj_name}'."
        if obj_type == "TABLE":
            return (
                f"DROP CONTAINER {obj_name} -- "
                f"[SDK: database.delete_container(container='{obj_name}')]"
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
        from core.state.sql_statement import SqlStatement

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

    # Story 27-3: CosmosDB DROP operations require the Azure SDK, not SQL execution.
    def requires_sdk_for_drop(self) -> bool:
        """True — Cosmos containers cannot be dropped via the native driver; the SDK is required."""
        return True

    # Story 27-3: annotation injected into generated scripts for SDK operations.
    def sdk_operation_hint_prefix(self) -> "Optional[str]":
        """``"-- [COSMOSDB SDK OPERATION]"`` — annotates SDK-routed statements in scripts."""
        return "-- [COSMOSDB SDK OPERATION]"

    def build_sdk_drop_operation(self, statement: object) -> "Optional[Dict[str, Any]]":
        """Build a CosmosDB delete_container SDK operation for a DROP statement."""
        sql = getattr(statement, "sql", "") or ""
        if "DROP CONTAINER" in sql.upper():
            container_name = getattr(statement, "object_name", None) or ""
            return {
                "operation": "delete_container",
                "container_name": container_name,
                "python_code": f"database.delete_container(container='{container_name}')",
                "warning": "This will DELETE ALL DATA in the container",
            }
        return None

    def generate_sdk_script(self, sdk_statements: "List[Any]") -> "Optional[str]":
        """Generate a CosmosDB Python SDK script block for sdk_statements."""
        from db.plugins.cosmosdb.sdk_translator import CosmosDbSdkTranslator

        dummy_translator = CosmosDbSdkTranslator(connection_manager=None)
        python_script = dummy_translator.generate_python_script(sdk_statements)
        header = (
            "\n\n"
            "-- ========================================\n"
            "-- COSMOSDB SDK OPERATIONS (Python)\n"
            "-- ========================================\n"
            "-- The following operations require Azure SDK and cannot be executed via SQL API\n"
            "-- Use the Python script below or execute via Azure Portal\n"
            "\n"
        )
        return header + python_script

    def type_equivalents(self) -> "Dict[str, str]":
        """CosmosDB has no relational type aliases — JSON documents store untyped values."""
        return {}

    def type_preferences(self) -> "Dict[str, str]":
        """CosmosDB has no preferred SQL types — values are JSON-typed at the document level."""
        return {}


__all__ = ["CosmosdbQuirks"]
