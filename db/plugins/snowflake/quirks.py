"""Snowflake :class:`DialectQuirks`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Type

from db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from core.sql_generator.alter.base_alter_generator import (
        BaseAlterGenerator,
    )
    from core.sql_generator.base_generator import BaseSqlGenerator


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
    table_drop_style = "if_exists_cascade"
    unquoted_identifier_case = "uppercase"
    quote_qualified_folds_to_uppercase = True
    connection_identifier_attrs = ("url", "account")
    missing_connection_identifier_hint = "Snowflake requires url or account"
    native_url_schema_params = ("schema",)
    native_driver_display = "snowflake-connector-python"
    pygments_lexer = "sql"

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

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """Snowflake rich DDL generation is registered by higher tiers."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """Snowflake ALTER generation is registered by higher tiers."""
        return None

    def introspector_class(self) -> Optional[Type[Any]]:
        """Snowflake rich introspection is registered by higher tiers."""
        return None

    def vendor_queries_class(self) -> Optional[Type[Any]]:
        """Snowflake metadata queries are registered by higher tiers."""
        return None


__all__ = ["SnowflakeQuirks"]
