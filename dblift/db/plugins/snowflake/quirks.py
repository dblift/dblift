"""Snowflake :class:`DialectQuirks`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from dblift.core.sql_parser.lexical_spec import LexicalSpec


class SnowflakeQuirks(BaseQuirks):
    """Snowflake-specific dialect behaviour."""

    supports_transactions = True
    supports_transactional_ddl = False
    schema_required = True
    uppercase_identifiers = True
    clean_strategy = "native"
    sqlglot_dialect = "snowflake"
    statement_facts_class = SqlglotStatementFactsReader
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
    lint_placeholder_url = "snowflake://localhost/DBLIFT_VALIDATE_SQL/PUBLIC"
    # D1 refuses every script-level control before execution; no begin/end envelope is qualified.
    transaction_control_sql_patterns = (
        (r"^BEGIN\b", "unsupported"),
        (r"^START\s+TRANSACTION\b", "unsupported"),
        (r"^(?:COMMIT|ROLLBACK)\b", "unsupported"),
    )

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

    def lexical_spec(self) -> "LexicalSpec":
        """Rules shared by execution and SQL analysis."""
        from dblift.db.plugins.snowflake.lexical_spec import SNOWFLAKE_SPEC

        return SNOWFLAKE_SPEC

    def blank_comments(self, sql: str) -> str:
        """Mask comments with the same scanner used for Snowflake execution."""
        from dblift.core.sql_parser.lexical_engine import LexicalEngine

        return LexicalEngine(self.lexical_spec()).blank_comments(sql)


__all__ = ["SnowflakeQuirks"]
