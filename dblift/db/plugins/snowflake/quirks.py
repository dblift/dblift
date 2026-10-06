"""Snowflake :class:`DialectQuirks`."""

from __future__ import annotations

from typing import Any, Optional

from dblift.db.base_quirks import BaseQuirks


class SnowflakeQuirks(BaseQuirks):
    """Snowflake-specific dialect behaviour."""

    supports_transactions = True
    supports_transactional_ddl = False
    schema_required = True
    uppercase_identifiers = True
    clean_strategy = "native"
    sqlglot_dialect = "snowflake"
    default_schema_name = "PUBLIC"
    drop_supports_if_exists = True
    unquoted_identifier_case = "uppercase"
    quote_qualified_folds_to_uppercase = True
    # Flyway creates ``"flyway_schema_history"`` quoted lowercase, which the
    # uppercase-folded history lookup cannot find.
    flyway_source_table_case_sensitive = True
    connection_identifier_attrs = ("url", "account")
    missing_connection_identifier_hint = "Snowflake requires url or account"
    native_url_schema_params = ("schema",)
    native_driver_display = "snowflake-connector-python"

    def __init__(self, dialect_name: str = "snowflake") -> None:
        super().__init__(dialect_name=dialect_name)

    def has_connection_identifier(self, database_config: Any) -> bool:
        """Snowflake accepts a URL or an account identifier."""
        if isinstance(database_config, dict):
            url = database_config.get("url")
            account = database_config.get("account")
            if not account:
                account = database_config.get("host")
        else:
            url = getattr(database_config, "url", None)
            account = getattr(database_config, "account", None) or getattr(
                database_config, "host", None
            )
        return bool(str(url or "").strip() or str(account or "").strip())

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Use Snowflake's sqlglot grammar for AST and current hybrid callers.

        Migration splitting preserves Snowflake quoting and refuses unquoted
        scripting blocks until their grammar is qualified.
        """
        if parser_type in {"hybrid", "sqlglot"}:
            from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from dblift.db.plugins.snowflake.statement_parser import SnowflakeStatementParser

            return SnowflakeStatementParser
        return None


__all__ = ["SnowflakeQuirks"]
